from __future__ import annotations

import time
from typing import Any

from easy_tdx import Market

from workbench.providers.tdx.catalog import _iter_response_rows
from workbench.providers.tdx.symbols import market_label, normalize_code, to_symbol


def _main_net_from_row(row: object) -> float:
    if isinstance(row, dict):
        for key in ("main_net_amount", "main_net", "main_cum"):
            if row.get(key) is not None:
                return float(row[key])
        return 0.0
    for key in ("main_net_amount", "main_net", "main_cum"):
        if hasattr(row, key):
            value = getattr(row, key)
            if value is not None:
                return float(value)
    return 0.0


def _change_pct_from_row(row: object) -> float:
    if isinstance(row, dict):
        price = float(row.get("close") or row.get("price") or 0.0)
        pre = float(row.get("pre_close") or 0.0)
    else:
        price = float(getattr(row, "close", None) or getattr(row, "price", 0.0) or 0.0)
        pre = float(getattr(row, "pre_close", 0.0) or 0.0)
    if pre <= 0:
        return 0.0
    return round((price - pre) / pre * 100.0, 4)


def _symbol_from_member_row(row: object) -> str | None:
    symbol = getattr(row, "symbol", None) or (row.get("symbol") if isinstance(row, dict) else None)
    if symbol:
        return str(symbol).strip().upper()
    if isinstance(row, dict):
        market = row.get("market", Market.SH)
        code = row.get("code", "")
    else:
        market = getattr(row, "market", Market.SH)
        code = getattr(row, "code", "")
    if isinstance(market, int):
        market = Market(market)
    code = normalize_code(str(code))
    if not code:
        return None
    return to_symbol(market_label(market), code)


_LIVE_MEMBER_CACHE: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}
_LIVE_MEMBER_CACHE_TTL_SECONDS = 5.0


def fetch_live_board_members(
    enhanced_client: object,
    sector_id: str,
    *,
    limit: int = 30,
    member_count: int | None = None,
) -> list[dict[str, Any]]:
    fetch_count = member_count or max(limit * 3, 100)
    raw_members = enhanced_client.get_board_members(sector_id, count=fetch_count)  # type: ignore[attr-defined]
    ranked: list[dict[str, Any]] = []
    for row in _iter_response_rows(raw_members):
        symbol = _symbol_from_member_row(row)
        if not symbol:
            continue
        name = str(getattr(row, "name", None) or (row.get("name") if isinstance(row, dict) else symbol))
        ranked.append(
            {
                "symbol": symbol,
                "name": name,
                "main_cumulative": _main_net_from_row(row),
                "change_pct": _change_pct_from_row(row),
            }
        )
    ranked.sort(key=lambda item: (-float(item["main_cumulative"]), item["symbol"]))
    return ranked[:limit]


def fetch_live_board_members_cached(
    enhanced_client: object,
    sector_id: str,
    *,
    limit: int = 30,
    member_count: int | None = None,
) -> list[dict[str, Any]]:
    cache_key = (sector_id, limit)
    now = time.monotonic()
    cached = _LIVE_MEMBER_CACHE.get(cache_key)
    if cached is not None and now - cached[0] < _LIVE_MEMBER_CACHE_TTL_SECONDS:
        return cached[1]
    ranked = fetch_live_board_members(
        enhanced_client,
        sector_id,
        limit=limit,
        member_count=member_count,
    )
    _LIVE_MEMBER_CACHE[cache_key] = (now, ranked)
    return ranked
