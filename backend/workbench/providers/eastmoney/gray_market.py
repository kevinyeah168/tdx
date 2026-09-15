from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

from workbench.providers.eastmoney.gray_flow_minutes import (
    format_gray_flow_minute,
    resolve_gray_flow_sampled_at,
)


@dataclass(frozen=True)
class StockGrayFlowSample:
    trade_date: str
    symbol: str
    code: str
    stock_name: str
    market: str
    open_net_inflow: float
    dark_net_inflow: float
    total_net_inflow: float
    sampled_at: datetime
    source: str


class GrayMarketProvider:
    source = "eastmoney:graymarket:darktrade"
    list_api = "https://quotederivates.eastmoney.com/datacenter/darktrade"
    direct_code_lookup_max = 8
    sector_code_fetch_retries = 3
    sector_code_fetch_workers = 4
    _board_cache: dict[str, tuple[float, dict[str, dict]]] = {}
    _board_cache_lock = threading.Lock()

    def fetch_full_market_gray_snapshots(
        self,
        *,
        trade_date: str,
        sampled_at: datetime | None = None,
        page_size: int = 100,
        max_pages: int = 120,
    ) -> list[StockGrayFlowSample]:
        """Paginate the East Money darktrade leaderboard (~5k rows in ~8s)."""
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        all_rows: list[dict] = []
        page = 1
        while page <= max_pages:
            payload = self._fetch_darktrade_payload(
                date=trade_date,
                start_page=page,
                num_per_page=page_size,
                datetype="2",
            )
            rows = payload.get("data")
            if not isinstance(rows, list) or not rows:
                break
            all_rows.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < page_size:
                break
            page += 1
        return self._rows_to_gray_flow_samples(
            trade_date=trade_date,
            rows=all_rows,
            sampled_at=sampled_at,
        )

    def fetch_stock_gray_flow_snapshots(
        self,
        *,
        trade_date: str,
        stocks: list[dict],
        sampled_at: datetime | None = None,
    ) -> list[StockGrayFlowSample]:
        if not stocks:
            return []
        wanted_codes = {
            str(stock.get("stockCode") or stock.get("stock_code") or stock.get("code") or "")
            .strip()
            .zfill(6)
            for stock in stocks
        }
        wanted_codes.discard("000000")
        if not wanted_codes:
            return []
        code_to_stock = {
            str(stock.get("stockCode") or stock.get("stock_code") or stock.get("code") or "")
            .strip()
            .zfill(6): stock
            for stock in stocks
        }
        board_rows = self._fetch_stock_board_rows_by_codes(date=trade_date, codes=wanted_codes)
        found_rows = [board_rows[code] for code in wanted_codes if code in board_rows]
        return self._rows_to_gray_flow_samples(
            trade_date=trade_date,
            rows=found_rows,
            sampled_at=sampled_at,
            code_to_stock=code_to_stock,
        )

    def _fetch_stock_board_rows_by_codes(
        self,
        *,
        date: str,
        codes: set[str],
    ) -> dict[str, dict]:
        if not codes:
            return {}

        def fetch_one(code: str) -> tuple[str, dict | None]:
            last_error: Exception | None = None
            for attempt in range(self.sector_code_fetch_retries):
                try:
                    payload = self._fetch_darktrade_payload(
                        date=date,
                        start_page=1,
                        num_per_page=1,
                        datetype="2",
                        code=code,
                    )
                    rows = payload.get("data")
                    if not isinstance(rows, list) or not rows:
                        return code, None
                    row = rows[0]
                    return code, row if isinstance(row, dict) else None
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.4 * (attempt + 1))
            if last_error is not None:
                return code, None
            return code, None

        board_rows: dict[str, dict] = {}
        workers = min(self.sector_code_fetch_workers, max(1, len(codes)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_one, code): code for code in codes}
            for future in as_completed(futures):
                try:
                    code, row = future.result()
                except Exception:
                    continue
                if row is not None:
                    board_rows[code] = row
        return board_rows

    def _rows_to_gray_flow_samples(
        self,
        *,
        trade_date: str,
        rows: list[dict],
        sampled_at: datetime | None = None,
        code_to_stock: dict[str, dict] | None = None,
    ) -> list[StockGrayFlowSample]:
        samples: list[StockGrayFlowSample] = []
        for row in rows:
            code = str(row.get("4") or row.get("code") or "").strip().zfill(6)
            if not code or code == "000000":
                continue
            stock = (code_to_stock or {}).get(code, {})
            stock_name = str(
                stock.get("displayName") or stock.get("display_name") or stock.get("name") or row.get("16") or code
            ).strip()
            market_flag = str(row.get("3", "")).strip()
            market = str(stock.get("market") or ("sh" if market_flag == "1" else "sz")).strip().lower()
            symbol = str(stock.get("symbol") or "").strip().upper()
            if not symbol:
                prefix = "SH" if market == "sh" else "SZ"
                symbol = f"{prefix}{code}"
            sampled = resolve_gray_flow_sampled_at(
                trade_date=trade_date,
                sampled_at=sampled_at,
                provider_update_raw=row.get("5"),
            )
            open_net_inflow = float(row.get("7") or 0)
            dark_net_inflow = float(row.get("6") or 0)
            total_net_inflow = float(row.get("8") or (open_net_inflow + dark_net_inflow))
            samples.append(
                StockGrayFlowSample(
                    trade_date=trade_date,
                    symbol=symbol,
                    code=code,
                    stock_name=stock_name,
                    market=market,
                    open_net_inflow=open_net_inflow,
                    dark_net_inflow=dark_net_inflow,
                    total_net_inflow=total_net_inflow,
                    sampled_at=sampled,
                    source=self.source,
                )
            )
        return samples

    def _fetch_darktrade_payload(
        self,
        *,
        date: str,
        start_page: int,
        num_per_page: int,
        sortflag: int = 6,
        descending: bool = True,
        market: str = "",
        datetype: str = "2",
        code: str | None = None,
    ) -> dict:
        try:
            from curl_cffi import requests
        except ImportError as exc:
            raise RuntimeError("curl_cffi is required for the gray market provider") from exc

        params = {
            "version": 100,
            "cver": 100,
            "date": date.replace("-", ""),
            "StartPage": start_page,
            "NumPerPage": num_per_page,
            "sortflag": sortflag,
            "desc": 1 if descending else 0,
            "market": market,
            "datetype": datetype,
        }
        if code:
            params["code"] = str(code).strip().upper()
        headers = {
            "Referer": "https://emrnweb.eastmoney.com/graymarket/home",
            "rnProjectId": "emrn.GrayMarketRank",
        }
        response = requests.get(
            self.list_api,
            params=params,
            headers=headers,
            impersonate="chrome",
            timeout=30,
        )
        response.raise_for_status()
        payload = self._decode_darktrade_payload(response)
        if not isinstance(payload, dict):
            return {}
        return payload

    @staticmethod
    def _decode_darktrade_payload(response) -> dict:
        raw = response.content
        last_error: Exception | None = None
        for encoding in ("utf-8", "gbk", "gb18030"):
            try:
                return json.loads(raw.decode(encoding))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                last_error = exc
        raise RuntimeError(f"eastmoney darktrade response is not valid JSON: {last_error}") from last_error

    @classmethod
    def clear_board_cache(cls) -> None:
        with cls._board_cache_lock:
            cls._board_cache.clear()

    @staticmethod
    def minute_from_sample(sample: StockGrayFlowSample) -> str:
        return format_gray_flow_minute(sample.sampled_at)
