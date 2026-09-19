from __future__ import annotations

from datetime import date as date_type
from math import fsum
from typing import Any

from workbench.collector.sector_gray_aggregator import SECTOR_GRAY_SOURCE
from workbench.collector.trading_clock import clip_minute_for_live_session
from workbench.domain import DataQuality
from workbench.services.custom_sectors import CustomSectorService
from workbench.storage.hot_store import CompleteFundCurve, HotStore
from workbench.storage.meta_store import MetaStore

FUND_TIERS = ("main", "super", "large", "medium", "small")
AGGREGATED_TIER_META = {
    tier: {"source": "constituent_sum", "quality": DataQuality.AGGREGATED.value}
    for tier in FUND_TIERS
}


def _exact_row_at(series: list[dict[str, Any]], minute: str) -> dict[str, Any] | None:
    for row in series:
        if str(row["minute"]) == minute:
            return row
    return None


def _forward_row_at(series: list[dict[str, Any]], minute: str) -> dict[str, Any] | None:
    last: dict[str, Any] | None = None
    for row in series:
        if str(row["minute"]) <= minute:
            last = row
        else:
            break
    return last


def _aggregate_fund_rows(
    stock_series: dict[str, list[dict[str, Any]]],
    members: list[str],
) -> list[dict[str, Any]]:
    minutes = sorted(
        {
            str(row["minute"])
            for symbol in members
            for row in stock_series.get(symbol, [])
        }
    )
    if not minutes:
        return []

    rows: list[dict[str, Any]] = []
    previous_cum: dict[str, float] | None = None
    for minute in minutes:
        totals = {f"{tier}_cum": 0.0 for tier in FUND_TIERS}
        change_values: list[float] = []
        covered = 0
        for symbol in members:
            row = _forward_row_at(stock_series.get(symbol, []), minute)
            if row is None:
                continue
            covered += 1
            for tier in FUND_TIERS:
                totals[f"{tier}_cum"] += float(row[f"{tier}_cum"])
            if row.get("change_pct") is not None:
                change_values.append(float(row["change_pct"]))
        if covered == 0:
            continue

        deltas = {
            f"{tier}_delta": totals[f"{tier}_cum"] - (previous_cum or {}).get(f"{tier}_cum", 0.0)
            for tier in FUND_TIERS
        }
        previous_cum = dict(totals)
        rows.append(
            {
                "minute": minute,
                **deltas,
                **totals,
                "change_pct": sum(change_values) / len(change_values) if change_values else 0.0,
                "close": None,
                "amount_delta": None,
                "tier_meta": AGGREGATED_TIER_META,
            }
        )
    return rows


def _aggregate_gray_rows(
    stock_series: dict[str, list[dict[str, Any]]],
    members: list[str],
    *,
    member_count: int,
) -> list[dict[str, Any]]:
    minutes = sorted(
        {
            str(row["minute"])
            for symbol in members
            for row in stock_series.get(symbol, [])
        }
    )
    rows: list[dict[str, Any]] = []
    for minute in minutes:
        covered: list[str] = []
        open_values: list[float] = []
        dark_values: list[float] = []
        total_values: list[float] = []
        for symbol in members:
            row = _exact_row_at(stock_series.get(symbol, []), minute)
            if row is None:
                continue
            covered.append(symbol)
            open_values.append(float(row["open_cum"]))
            dark_values.append(float(row["dark_cum"]))
            total_values.append(float(row["total_cum"]))
        if not covered:
            continue
        rows.append(
            {
                "minute": minute,
                "member_count": member_count,
                "gray_covered_count": len(covered),
                "open_cum": fsum(open_values),
                "dark_cum": fsum(dark_values),
                "total_cum": fsum(total_values),
                "source": SECTOR_GRAY_SOURCE,
                "quality": DataQuality.AGGREGATED.value,
            }
        )
    return rows


class CustomSectorFlowService:
    def __init__(self, meta: MetaStore, hot: HotStore) -> None:
        self._meta = meta
        self._hot = hot
        self._custom = CustomSectorService(meta)

    def members(self, sector_id: str) -> list[str]:
        return self._custom.symbols_for(sector_id)

    def complete_fund_curve(self, trade_date: str, sector_id: str) -> CompleteFundCurve:
        members = self.members(sector_id)
        if not members:
            return CompleteFundCurve(latest_complete_minute=None, rows=[])
        stock_series = {
            symbol: self._hot.stock_fund_series(trade_date, symbol)
            for symbol in members
        }
        rows = _aggregate_fund_rows(stock_series, members)
        latest = self._hot.latest_complete_minute(trade_date)
        if latest is None and rows:
            latest = str(rows[-1]["minute"])
        latest = clip_minute_for_live_session(
            date_type.fromisoformat(trade_date),
            latest,
        )
        return CompleteFundCurve(latest_complete_minute=latest, rows=rows)

    def sector_gray_curve(self, trade_date: str, sector_id: str) -> CompleteFundCurve:
        members = self.members(sector_id)
        if not members:
            return CompleteFundCurve(latest_complete_minute=None, rows=[])
        stock_series = {
            symbol: self._hot.stock_gray_curve(trade_date, symbol).rows
            for symbol in members
        }
        rows = _aggregate_gray_rows(
            stock_series,
            members,
            member_count=len(members),
        )
        latest = rows[-1]["minute"] if rows else None
        latest = clip_minute_for_live_session(
            date_type.fromisoformat(trade_date),
            str(latest) if latest else None,
        )
        return CompleteFundCurve(latest_complete_minute=latest, rows=rows)

    def fund_tip_at_minute(
        self,
        trade_date: str,
        sector_id: str,
        minute: str,
    ) -> dict[str, Any] | None:
        series = self.complete_fund_curve(trade_date, sector_id).rows
        if not series:
            return None
        for row in reversed(series):
            if str(row["minute"]) <= minute:
                return row
        return series[-1]
