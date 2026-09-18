"""Build market-scope minute rows from TDX yuntu real_hq snapshots."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from workbench.domain import DataQuality, MarketScopeMinute, TierPoint
from workbench.providers.tdx.yuntu_minute_records import (
    YUNTU_SOURCE,
    _gap_tier_point,
    _official_funds,
    change_pct_from_dqzf,
    index_yuntu_rows_by_code,
    main_yuan_from_wan,
)
from workbench.providers.tdx.yuntu_sector_flow import YuntuStockQuote, is_sector_index_code

MarketScopeKey = Literal["hs", "sh", "kc", "sz", "cy"]

MARKET_SCOPE_ORDER: tuple[MarketScopeKey, ...] = ("hs", "sh", "kc", "sz", "cy")

MARKET_SCOPE_LABELS: dict[MarketScopeKey, str] = {
    "hs": "沪深",
    "sh": "沪市",
    "kc": "科创",
    "sz": "深市",
    "cy": "创业",
}

# TDX yuntu special sector codes for market-wide main cumulative flow.
MARKET_SCOPE_SECTOR_CODES: dict[MarketScopeKey, str | None] = {
    "hs": "880001",
    "sh": "880011",
    "kc": "880041",
    "sz": None,
    "cy": "880031",
}

_SHENZHEN_STOCK_CODE = re.compile(r"^00\d{4}$")


def is_shenzhen_main_stock_code(code: str) -> bool:
    normalized = code.strip()
    if not normalized or is_sector_index_code(normalized):
        return False
    return _SHENZHEN_STOCK_CODE.fullmatch(normalized) is not None


def _aggregated_funds(delta: float, cumulative: float) -> TierPoint:
    return TierPoint(
        delta=delta,
        cumulative=cumulative,
        source=YUNTU_SOURCE,
        quality=DataQuality.AGGREGATED,
    )


def _aggregated_official_funds(delta: float, cumulative: float):
    official = _aggregated_funds(delta, cumulative)
    gap = _gap_tier_point(0.0)
    from workbench.domain import FundFlow

    return FundFlow(main=official, super=gap, large=gap, medium=gap, small=gap)


def _sector_scope_snapshot(
    indexed: dict[str, YuntuStockQuote],
    sector_code: str,
) -> tuple[float, float] | None:
    row = indexed.get(sector_code)
    if row is None:
        return None
    return main_yuan_from_wan(row.f_amo_sum_wan), change_pct_from_dqzf(row.dqzf)


def _shenzhen_scope_snapshot(
    indexed: dict[str, YuntuStockQuote],
) -> tuple[float, float]:
    total_wan = 0.0
    change_sum = 0.0
    count = 0
    for code, row in indexed.items():
        if not is_shenzhen_main_stock_code(code):
            continue
        total_wan += float(row.f_amo_sum_wan)
        change_sum += float(row.dqzf)
        count += 1
    main_cum = main_yuan_from_wan(total_wan)
    change_pct = round((change_sum / count) * 100.0, 2) if count else 0.0
    return main_cum, change_pct


def build_market_scope_minutes_from_yuntu(
    *,
    trade_date: date,
    minute: str,
    rows: list[YuntuStockQuote],
    previous_main_cum: dict[str, float],
    observed_at: datetime,
    batch_id: str,
) -> list[MarketScopeMinute]:
    indexed = index_yuntu_rows_by_code(rows)
    records: list[MarketScopeMinute] = []

    for scope in MARKET_SCOPE_ORDER:
        sector_code = MARKET_SCOPE_SECTOR_CODES[scope]
        if sector_code is not None:
            snapshot = _sector_scope_snapshot(indexed, sector_code)
            if snapshot is None:
                continue
            main_cum, change_pct = snapshot
            funds = _official_funds(
                main_cum - previous_main_cum.get(scope, 0.0),
                main_cum,
            )
        else:
            main_cum, change_pct = _shenzhen_scope_snapshot(indexed)
            main_delta = main_cum - previous_main_cum.get(scope, 0.0)
            funds = _aggregated_official_funds(main_delta, main_cum)

        records.append(
            MarketScopeMinute(
                trade_date=trade_date,
                minute=minute,
                scope=scope,
                change_pct=change_pct,
                funds=funds,
                observed_at=observed_at,
                batch_id=batch_id,
            )
        )
    return records


def build_gap_market_scope_minutes(
    *,
    trade_date: date,
    minute: str,
    previous_main_cum: dict[str, float],
    observed_at: datetime,
    batch_id: str,
) -> list[MarketScopeMinute]:
    from workbench.providers.tdx.yuntu_minute_records import _gap_funds

    records: list[MarketScopeMinute] = []
    for scope in MARKET_SCOPE_ORDER:
        cumulative = previous_main_cum.get(scope, 0.0)
        records.append(
            MarketScopeMinute(
                trade_date=trade_date,
                minute=minute,
                scope=scope,
                change_pct=0.0,
                funds=_gap_funds(cumulative),
                observed_at=observed_at,
                batch_id=batch_id,
            )
        )
    return records
