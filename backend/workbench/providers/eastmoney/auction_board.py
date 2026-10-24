from __future__ import annotations

import threading
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
from workbench.providers.eastmoney.push2_client import http_get_push2, reset_visitor_cookie

AUCTION_BOARD_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
AUCTION_BOARD_FIELDS = "f12,f13,f14,f2,f3,f5,f6,f10,f17,f63"
AUCTION_BOARD_UT = "bd1d9ddb04089700cf9c27f6f7426281"
AUCTION_BOARD_RANK_LIMIT = 100
AUCTION_BOARD_TOP_LIMIT = 200
AUCTION_BOARD_PAGE_SIZE = 100
AUCTION_BOARD_MAX_ITEMS = 6000
AUCTION_BOARD_PAGE_DELAY_SECONDS = 0.12
AUCTION_CLIST_REFERER = "https://quote.eastmoney.com/center/gridlist.html"
CLIST_PAGE_RETRIES = 6
CLIST_RETRY_DELAY_SECONDS = 0.4
CLIST_REQUEST_TIMEOUT_SECONDS = 15.0

CLIST_PATH = "/api/qt/clist/get"
# push2 may reject bare clients; try a small set per request to avoid anti-bot triggers.
CLIST_ENDPOINTS = (
    f"https://push2delay.eastmoney.com{CLIST_PATH}",
    f"https://push2.eastmoney.com{CLIST_PATH}",
) + tuple(
    f"https://{host}.push2.eastmoney.com{CLIST_PATH}"
    for host in (126, 48, 80, 125, 124)
)
CLIST_MAX_ATTEMPTS = 4

_clist_endpoint_lock = threading.Lock()
_clist_working_endpoint: str | None = None
_clist_working_expires_at = 0.0

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
        # clist may be blocked and darktrade often has no same-day rows until after 09:25.
        return [], self.darktrade_source

    def fetch_all_market(
        self,
        *,
        trade_date: str,
        sort_key: str = AUCTION_BOARD_DEFAULT_SORT,
        rank_side: str = "desc",
    ) -> tuple[list[EastMoneyAuctionBoardRow], str]:
        key = sort_key if sort_key in AUCTION_BOARD_SORT_KEYS else AUCTION_BOARD_DEFAULT_SORT
        clist_error: Exception | None = None
        try:
            rows = self._fetch_clist_all_pages(sort_key=key, rank_side=rank_side)
            if rows:
                return rows, self.source
        except Exception as exc:  # noqa: BLE001 — fall back to darktrade
            clist_error = exc

        rows = self._fetch_darktrade_all_pages(trade_date=trade_date, sort_key=key)
        if rows:
            return rows, self.darktrade_source
        return [], self.darktrade_source

    def _fetch_clist_rank(
        self,
        *,
        sort_key: str,
        limit: int,
        rank_side: str,
    ) -> list[EastMoneyAuctionBoardRow]:
        return self._fetch_clist_page(
            sort_key=sort_key,
            page=1,
            page_size=limit,
            rank_side=rank_side,
            limit=limit,
        )

    def _fetch_clist_all_pages(
        self,
        *,
        sort_key: str,
        rank_side: str,
    ) -> list[EastMoneyAuctionBoardRow]:
        page_size = AUCTION_BOARD_PAGE_SIZE
        collected: list[EastMoneyAuctionBoardRow] = []
        seen: set[str] = set()
        page = 1
        while len(collected) < AUCTION_BOARD_MAX_ITEMS:
            try:
                rows = self._fetch_clist_page(
                    sort_key=sort_key,
                    page=page,
                    page_size=page_size,
                    rank_side=rank_side,
                    limit=page_size,
                )
            except Exception:
                if collected:
                    break
                raise
            if not rows:
                break
            for row in rows:
                if row.code in seen:
                    continue
                seen.add(row.code)
                collected.append(row)
            if len(rows) < page_size:
                break
            page += 1
            time.sleep(AUCTION_BOARD_PAGE_DELAY_SECONDS)
        return collected

    def _fetch_clist_page(
        self,
        *,
        sort_key: str,
        page: int,
        page_size: int,
        rank_side: str,
        limit: int,
    ) -> list[EastMoneyAuctionBoardRow]:
        po = "1" if rank_side == "desc" else "0"
        fid = AUCTION_BOARD_SORT_PARAMS[sort_key]
        params = {
            "pn": str(max(1, page)),
            "pz": str(page_size),
            "po": po,
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": fid,
            "fs": AUCTION_BOARD_FS,
            "fields": AUCTION_BOARD_FIELDS,
            "ut": AUCTION_BOARD_UT,
        }
        last_error: Exception | None = None
        for attempt in range(CLIST_PAGE_RETRIES):
            for index, endpoint in enumerate(_iter_clist_endpoints()):
                if index >= CLIST_MAX_ATTEMPTS:
                    break
                try:
                    rows = self._request_clist_endpoint(endpoint, params=params, limit=limit)
                    if rows:
                        _remember_clist_endpoint(endpoint)
                        return rows
                    last_error = RuntimeError("eastmoney auction clist returned empty diff")
                except Exception as exc:  # noqa: BLE001 — try next endpoint
                    last_error = exc
            if attempt + 1 < CLIST_PAGE_RETRIES:
                reset_visitor_cookie()
                time.sleep(CLIST_RETRY_DELAY_SECONDS * (attempt + 1))
        if page == 1:
            reset_visitor_cookie()
            raise RuntimeError(f"eastmoney auction clist request failed: {last_error}") from last_error
        return []

    def _request_clist_endpoint(
        self,
        endpoint: str,
        *,
        params: dict[str, str],
        limit: int,
    ) -> list[EastMoneyAuctionBoardRow]:
        payload = http_get_push2(
            endpoint,
            params=params,
            referer=AUCTION_CLIST_REFERER,
            timeout=CLIST_REQUEST_TIMEOUT_SECONDS,
        )
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
        return rows

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

        if not collected and sort_key != "ratio":
            return self._fetch_darktrade_rank(trade_date=trade_date, sort_key="ratio", limit=limit)

        collected = _sort_rows(collected, sort_key, descending=True)
        return collected[:limit]

    def _fetch_darktrade_all_pages(
        self,
        *,
        trade_date: str,
        sort_key: str,
    ) -> list[EastMoneyAuctionBoardRow]:
        normalized_date = trade_date.strip().replace("-", "")
        sortflag = DARKTRADE_SORTFLAG.get(sort_key, 6)
        collected: list[EastMoneyAuctionBoardRow] = []
        seen: set[str] = set()
        page = 1
        while len(collected) < AUCTION_BOARD_MAX_ITEMS:
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
                if item is None or item.code in seen:
                    continue
                seen.add(item.code)
                collected.append(item)
            if len(raw_rows) < 100:
                break
            page += 1
            time.sleep(AUCTION_BOARD_PAGE_DELAY_SECONDS)
        if not collected and sort_key != "ratio":
            return self._fetch_darktrade_all_pages(trade_date=trade_date, sort_key="ratio")
        return collected

    def _parse_clist_row(self, row: dict[str, Any]) -> EastMoneyAuctionBoardRow | None:
        code = str(row.get("f12") or "").strip()
        if not code:
            return None
        name = str(row.get("f14") or code).strip() or code
        market = _to_int(row.get("f13"))
        price = _to_float(row.get("f2"))
        if price is None or price <= 0:
            price = _to_float(row.get("f17"))
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


def _iter_clist_endpoints() -> list[str]:
    global _clist_working_endpoint, _clist_working_expires_at
    now = time.monotonic()
    with _clist_endpoint_lock:
        if _clist_working_endpoint and now < _clist_working_expires_at:
            return [_clist_working_endpoint, *[ep for ep in CLIST_ENDPOINTS if ep != _clist_working_endpoint]]
    return list(CLIST_ENDPOINTS)


def _remember_clist_endpoint(endpoint: str, ttl: float = 300.0) -> None:
    global _clist_working_endpoint, _clist_working_expires_at
    with _clist_endpoint_lock:
        _clist_working_endpoint = endpoint
        _clist_working_expires_at = time.monotonic() + ttl
