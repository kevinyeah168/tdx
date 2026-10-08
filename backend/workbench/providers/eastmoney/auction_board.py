from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from workbench.collector.trading_clock import (
    AUCTION_BOARD_DEFAULT_SORT,
    AUCTION_BOARD_SORT_KEYS,
    AUCTION_BOARD_SORT_PARAMS,
    SHANGHAI,
)
from workbench.providers.eastmoney.gray_market import GrayMarketProvider

AUCTION_BOARD_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
AUCTION_BOARD_FIELDS = "f12,f13,f14,f2,f3,f5,f6,f10,f63"
AUCTION_BOARD_UT = "bd1d9ddb04089700cf9c27f6f7426281"
AUCTION_BOARD_RANK_LIMIT = 100

CLIST_ENDPOINTS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://push2delay.eastmoney.com/api/qt/clist/get",
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://7.push2.eastmoney.com/api/qt/clist/get",
)

DARKTRADE_SORTFLAG = {
    "ratio": 4,
    "amount": 7,
    "change": 3,
    "volume": 5,
    "price": 2,
}


@dataclass(frozen=True)
class EastMoneyAuctionBoardRow:
    symbol: str
    code: str
    name: str
    price: float | None
    change_pct: float | None
    volume_ratio: float | None
    amount: float | None
    volume: float | None
    market: int | None = None
    open_net_inflow: float | None = None


class EastMoneyAuctionBoardProvider:
    source = "eastmoney:auction:clist"
    darktrade_source = "eastmoney:auction:darktrade"

    def __init__(self, *, gray_provider: GrayMarketProvider | None = None) -> None:
        self._gray_provider = gray_provider or GrayMarketProvider()

    def fetch_rank(
        self,
        *,
        trade_date: str,
        sort_key: str = AUCTION_BOARD_DEFAULT_SORT,
        limit: int = AUCTION_BOARD_RANK_LIMIT,
        rank_side: str = "desc",
    ) -> tuple[list[EastMoneyAuctionBoardRow], str]:
        key = sort_key if sort_key in AUCTION_BOARD_SORT_KEYS else AUCTION_BOARD_DEFAULT_SORT
        lim = max(1, min(int(limit), AUCTION_BOARD_RANK_LIMIT))
        clist_error: Exception | None = None
        try:
            rows = self._fetch_clist_rank(sort_key=key, limit=lim, rank_side=rank_side)
            if rows:
                return rows, self.source
        except Exception as exc:  # noqa: BLE001 — fall back to darktrade
            clist_error = exc

        rows = self._fetch_darktrade_rank(trade_date=trade_date, sort_key=key, limit=lim)
        if rows:
            return rows, self.darktrade_source
        if clist_error is not None:
            raise RuntimeError(
                f"eastmoney auction clist request failed: {clist_error}; darktrade returned no rows"
            ) from clist_error
        return [], self.darktrade_source

    def _fetch_clist_rank(
        self,
        *,
        sort_key: str,
        limit: int,
        rank_side: str,
    ) -> list[EastMoneyAuctionBoardRow]:
        po = "1" if rank_side == "desc" else "0"
        fid = AUCTION_BOARD_SORT_PARAMS[sort_key]
        params = {
            "pn": "1",
            "pz": str(limit),
            "po": po,
            "np": "1",
            "fltt": "2",
            "invt": "0",
            "fid": fid,
            "fs": AUCTION_BOARD_FS,
            "fields": AUCTION_BOARD_FIELDS,
            "ut": AUCTION_BOARD_UT,
            "_": str(int(time.time() * 1000)),
        }
        headers = {
            "Referer": "https://quote.eastmoney.com/center/gridlist.html",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        last_error: Exception | None = None
        for endpoint in CLIST_ENDPOINTS:
            for attempt in range(3):
                try:
                    response = self._http_get(endpoint, params=params, headers=headers)
                    payload = response.json()
                    data = (payload or {}).get("data") or {}
                    diff = data.get("diff") or []
                    rows: list[EastMoneyAuctionBoardRow] = []
                    for raw in diff:
                        if not isinstance(raw, dict):
                            continue
                        item = self._parse_clist_row(raw)
                        if item is not None:
                            rows.append(item)
                        if len(rows) >= limit:
                            break
                    if rows:
                        return rows
                    last_error = RuntimeError("eastmoney auction clist returned empty diff")
                except Exception as exc:  # noqa: BLE001 — retry / try next endpoint
                    last_error = exc
                    if attempt < 2:
                        time.sleep(0.35 * (attempt + 1))
        raise RuntimeError(f"eastmoney auction clist request failed: {last_error}") from last_error

    def _fetch_darktrade_rank(
        self,
        *,
        trade_date: str,
        sort_key: str,
        limit: int,
    ) -> list[EastMoneyAuctionBoardRow]:
        normalized_date = trade_date.strip().replace("-", "")
        sortflag = DARKTRADE_SORTFLAG.get(sort_key, 6)
        collected: list[EastMoneyAuctionBoardRow] = []
        max_pages = max(2, min(6, (limit + 99) // 100))
        for page in range(1, max_pages + 1):
            payload = self._gray_provider._fetch_darktrade_payload(
                date=normalized_date,
                start_page=page,
                num_per_page=100,
                sortflag=sortflag,
                datetype="2",
            )
            raw_rows = payload.get("data")
            if not isinstance(raw_rows, list) or not raw_rows:
                break
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    continue
                item = self._parse_darktrade_row(raw)
                if item is not None:
                    collected.append(item)
            if len(raw_rows) < 100:
                break

        if not collected and sortflag != 6:
            return self._fetch_darktrade_rank(trade_date=trade_date, sort_key="ratio", limit=limit)

        collected = _sort_rows(collected, sort_key, descending=True)
        return collected[:limit]

    def _http_get(self, url: str, *, params: dict[str, str], headers: dict[str, str]):
        try:
            from curl_cffi import requests
        except ImportError as exc:
            raise RuntimeError("curl_cffi is required for the auction board provider") from exc
        response = requests.get(
            url,
            params=params,
            timeout=30,
            impersonate="chrome",
            headers=headers,
        )
        if response.status_code != 200:
            raise RuntimeError(f"eastmoney auction clist failed with status {response.status_code}")
        return response

    def _parse_clist_row(self, row: dict[str, Any]) -> EastMoneyAuctionBoardRow | None:
        code = str(row.get("f12") or "").strip()
        if not code:
            return None
        name = str(row.get("f14") or code).strip() or code
        market = _to_int(row.get("f13"))
        price = _to_float(row.get("f2"))
        amount_auction = _to_float(row.get("f63"))
        amount_turnover = _to_float(row.get("f6"))
        if amount_auction is not None and abs(amount_auction) > 1e-6:
            amount = amount_auction
        else:
            amount = amount_turnover
        volume = _to_float(row.get("f5"))
        if volume is None and amount is not None and price is not None and price > 0:
            volume = amount / (price * 100.0)
        return EastMoneyAuctionBoardRow(
            symbol=_to_symbol(code, market),
            code=code,
            name=name,
            price=price,
            change_pct=_to_float(row.get("f3")),
            volume_ratio=_to_float(row.get("f10")),
            amount=amount,
            volume=volume,
            market=market,
        )

    def _parse_darktrade_row(self, row: dict[str, Any]) -> EastMoneyAuctionBoardRow | None:
        code = str(row.get("4") or row.get("code") or "").strip().zfill(6)
        if not code or code == "000000":
            return None
        name = str(row.get("16") or code).strip() or code
        market_flag = _to_int(row.get("3"))
        open_net_inflow = _to_float(row.get("7"))
        amount = open_net_inflow
        total_amount = _to_float(row.get("8"))
        if amount is None and total_amount is not None:
            amount = total_amount
        price = _to_float(row.get("12"))
        return EastMoneyAuctionBoardRow(
            symbol=_to_symbol(code, market_flag),
            code=code,
            name=name,
            price=price if price and price > 0 else None,
            change_pct=_normalize_darktrade_change_pct(_to_float(row.get("11"))),
            volume_ratio=_to_float(row.get("14")),
            amount=amount,
            volume=_to_float(row.get("13")),
            market=market_flag,
            open_net_inflow=open_net_inflow,
        )


def _sort_rows(
    rows: list[EastMoneyAuctionBoardRow],
    sort_key: str,
    *,
    descending: bool,
) -> list[EastMoneyAuctionBoardRow]:
    field_map = {
        "ratio": lambda row: row.volume_ratio,
        "amount": lambda row: row.amount,
        "change": lambda row: row.change_pct,
        "volume": lambda row: row.volume,
        "price": lambda row: row.price,
    }
    getter = field_map.get(sort_key, field_map["ratio"])

    def sort_key_fn(row: EastMoneyAuctionBoardRow) -> tuple[int, float]:
        value = getter(row)
        if value is None or not isinstance(value, (int, float)):
            return (1, 0.0)
        return (0, float(value))

    return sorted(rows, key=sort_key_fn, reverse=descending)


def _normalize_darktrade_change_pct(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) <= 3.0:
        return value * 100.0
    return value


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "None", "null"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _to_symbol(code: str, market: int | None) -> str:
    if market == 1:
        return f"SH{code}"
    if market == 0:
        return f"SZ{code}"
    if market == 2 or code.startswith(("8", "4")):
        return f"BJ{code}"
    if code.startswith("6"):
        return f"SH{code}"
    return f"SZ{code}"


def auction_fetched_at_iso() -> str:
    return datetime.now(tz=SHANGHAI).isoformat()
