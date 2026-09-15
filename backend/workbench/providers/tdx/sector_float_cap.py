from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from workbench.providers.tdx.catalog import _iter_response_rows
from workbench.providers.tdx.symbols import market_from_label, parse_symbol

# Cache only 自由流通股本 (万股). Price / avg must stay live so 净比 moves with quotes.
_SYMBOL_SHARES_CACHE: dict[str, tuple[float, float]] = {}
_SYMBOL_SHARES_TTL_SECONDS = 3600.0
_QUOTE_BATCH_SIZE = 80


@dataclass(frozen=True, slots=True)
class SymbolFreeFloatCaps:
    """自由流通市值：现价口径 + 均价口径（元）。"""

    live: float
    avg: float


def _row_value(row: object, key: str, default: object = None) -> object:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def free_float_shares_wan_from_quote_row(row: object) -> float:
    """自由流通股本（万股）. Prefer circulating_capital_z over float_shares."""
    return float(
        _row_value(row, "circulating_capital_z", None)
        or _row_value(row, "float_shares", 0.0)
        or 0.0
    )


def live_price_from_quote_row(row: object) -> float:
    """Latest trade price for free-float market cap.

    Prefer live ``price``; ``close`` is often previous close during the session
    and would freeze 自由流通市值 / 净比 all day.
    """
    return float(
        _row_value(row, "price", None)
        or _row_value(row, "last", None)
        or _row_value(row, "close", None)
        or 0.0
    )


def avg_price_from_quote_row(row: object) -> float:
    """Session VWAP / 均价 from quote.

    Prefer explicit avg fields; else amount / (vol×100) for A-share 手.
    Falls back to live price when volume/amount unavailable.
    """
    for key in ("avg_price", "average_price", "vwap", "avg"):
        raw = _row_value(row, key, None)
        if raw is None:
            continue
        value = float(raw or 0.0)
        if value > 0:
            return value
    amount = float(_row_value(row, "amount", None) or _row_value(row, "turnover", 0.0) or 0.0)
    vol = float(_row_value(row, "vol", None) or _row_value(row, "volume", 0.0) or 0.0)
    if amount > 0 and vol > 0:
        return amount / (vol * 100.0)
    return live_price_from_quote_row(row)


def free_float_cap_from_quote_row(row: object) -> float:
    float_shares = free_float_shares_wan_from_quote_row(row)
    price = live_price_from_quote_row(row)
    if float_shares <= 0 or price <= 0:
        return 0.0
    # TDX share fields above are in 万股 (10k shares).
    return float_shares * 10_000.0 * price


def free_float_cap_avg_from_quote_row(row: object) -> float:
    float_shares = free_float_shares_wan_from_quote_row(row)
    avg_price = avg_price_from_quote_row(row)
    if float_shares <= 0 or avg_price <= 0:
        return 0.0
    return float_shares * 10_000.0 * avg_price


def _quote_tuple(symbol: str) -> tuple[int, str]:
    market_label, code = parse_symbol(symbol)
    market = market_from_label(market_label)
    return int(market), code


def _resolve_shares_wan(symbol: str, row: object, now: float) -> float:
    shares_wan = free_float_shares_wan_from_quote_row(row)
    if shares_wan > 0:
        _SYMBOL_SHARES_CACHE[symbol] = (now, shares_wan)
        return shares_wan
    cached = _SYMBOL_SHARES_CACHE.get(symbol)
    if cached is not None and now - cached[0] < _SYMBOL_SHARES_TTL_SECONDS:
        return cached[1]
    return 0.0


def build_symbol_free_float_cap_details(
    quote_client: object,
    symbols: list[str],
) -> dict[str, SymbolFreeFloatCaps]:
    """Build live-price and avg-price free-float caps; cache shares only."""
    if not symbols:
        return {}

    get_quotes = getattr(quote_client, "get_stock_quotes", None)
    if get_quotes is None:
        return {}

    unique_symbols = list(dict.fromkeys(symbols))
    now = time.monotonic()
    caps: dict[str, SymbolFreeFloatCaps] = {}

    for offset in range(0, len(unique_symbols), _QUOTE_BATCH_SIZE):
        batch = unique_symbols[offset : offset + _QUOTE_BATCH_SIZE]
        try:
            response = get_quotes([_quote_tuple(symbol) for symbol in batch])
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        for row in _iter_response_rows(response):
            code = str(_row_value(row, "code", "")).strip()
            market = int(_row_value(row, "market", -1))
            if not code:
                continue
            market_label = {0: "SZ", 1: "SH", 2: "BJ"}.get(market)
            if not market_label:
                continue
            symbol = f"{market_label}{code}"
            shares_wan = _resolve_shares_wan(symbol, row, now)
            price = live_price_from_quote_row(row)
            avg_price = avg_price_from_quote_row(row)
            if shares_wan <= 0:
                continue
            live_cap = shares_wan * 10_000.0 * price if price > 0 else 0.0
            avg_cap = shares_wan * 10_000.0 * avg_price if avg_price > 0 else 0.0
            if live_cap <= 0 and avg_cap <= 0:
                continue
            caps[symbol] = SymbolFreeFloatCaps(live=live_cap, avg=avg_cap)

    return caps


def build_symbol_free_float_caps(
    quote_client: object,
    symbols: list[str],
) -> dict[str, float]:
    """Backward-compatible live-price free-float caps."""
    return {
        symbol: detail.live
        for symbol, detail in build_symbol_free_float_cap_details(quote_client, symbols).items()
        if detail.live > 0
    }


def sector_free_float_market_caps(
    memberships_for: Any,
    sector_ids: list[str],
    symbol_caps: dict[str, float],
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for sector_id in sector_ids:
        members = memberships_for(sector_id)
        totals[sector_id] = sum(symbol_caps.get(symbol, 0.0) for symbol in members)
    return totals
