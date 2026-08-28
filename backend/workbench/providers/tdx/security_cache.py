from __future__ import annotations

from typing import Any


def load_easy_tdx_security_cache() -> list[dict[str, Any]] | None:
    try:
        from easy_tdx.client import _load_cache
    except ImportError:
        return None

    cached = _load_cache()
    if not cached:
        return None

    rows: list[dict[str, Any]] = []
    for stock in cached:
        market = stock.market.name if hasattr(stock.market, "name") else str(stock.market)
        rows.append(
            {
                "market": market,
                "code": str(stock.code).zfill(6),
                "name": str(getattr(stock, "name", stock.code)),
            }
        )
    return rows
