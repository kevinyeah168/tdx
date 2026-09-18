"""Build stock/sector minute rows from TDX yuntu real_hq snapshots."""
from __future__ import annotations

from datetime import date, datetime

from workbench.domain import DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
from workbench.providers.tdx.yuntu_sector_flow import (
    WAN_YUAN_TO_YUAN,
    YuntuStockQuote,
    is_sector_index_code,
)

YUNTU_SOURCE = "tdx.yuntu.real_hq"
GAP_SOURCE = "-"
GAP_BATCH_MARKER = "yuntu-gap"


def main_yuan_from_wan(value_wan: float) -> float:
    return float(value_wan) * WAN_YUAN_TO_YUAN


def change_pct_from_dqzf(dqzf: float) -> float:
    return round(float(dqzf) * 100.0, 2)


def index_yuntu_rows_by_code(rows: list[YuntuStockQuote]) -> dict[str, YuntuStockQuote]:
    indexed: dict[str, YuntuStockQuote] = {}
    for row in rows:
        code = row.stockcode.strip()
        if not code:
            continue
        indexed[code] = row
    return indexed


def _official_tier_point(delta: float, cumulative: float) -> TierPoint:
    return TierPoint(
        delta=delta,
        cumulative=cumulative,
        source=YUNTU_SOURCE,
        quality=DataQuality.OFFICIAL,
    )


def _gap_tier_point(cumulative: float) -> TierPoint:
    return TierPoint(
        delta=0.0,
        cumulative=cumulative,
        source=GAP_SOURCE,
        quality=DataQuality.GAP,
    )


def _gap_funds(cumulative: float) -> FundFlow:
    gap = _gap_tier_point(cumulative)
    return FundFlow(main=gap, super=gap, large=gap, medium=gap, small=gap)


def _official_funds(delta: float, cumulative: float) -> FundFlow:
    official = _official_tier_point(delta, cumulative)
    gap = TierPoint(delta=0.0, cumulative=0.0, source=GAP_SOURCE, quality=DataQuality.GAP)
    return FundFlow(main=official, super=gap, large=gap, medium=gap, small=gap)


def build_stock_minutes_from_yuntu(
    *,
    trade_date: date,
    minute: str,
    rows: list[YuntuStockQuote],
    code_to_symbol: dict[str, str],
    previous_main_cum: dict[str, float],
    observed_at: datetime,
    batch_id: str,
) -> list[StockMinute]:
    indexed = index_yuntu_rows_by_code(rows)
    records: list[StockMinute] = []
    for code, symbol in sorted(code_to_symbol.items()):
        row = indexed.get(code)
        if row is None or is_sector_index_code(code):
            continue
        main_cum = main_yuan_from_wan(row.f_amo_sum_wan)
        main_delta = main_cum - previous_main_cum.get(symbol, 0.0)
        records.append(
            StockMinute(
                trade_date=trade_date,
                minute=minute,
                symbol=symbol,
                close=max(float(row.now), 0.0),
                change_pct=change_pct_from_dqzf(row.dqzf),
                amount_delta=0.0,
                funds=_official_funds(main_delta, main_cum),
                observed_at=observed_at,
                batch_id=batch_id,
            )
        )
    return records


def build_sector_minutes_from_yuntu(
    *,
    trade_date: date,
    minute: str,
    rows: list[YuntuStockQuote],
    sector_ids: list[str],
    member_counts: dict[str, int],
    previous_main_cum: dict[str, float],
    observed_at: datetime,
    batch_id: str,
) -> list[SectorMinute]:
    indexed = index_yuntu_rows_by_code(rows)
    records: list[SectorMinute] = []
    for sector_id in sorted(sector_ids):
        row = indexed.get(sector_id)
        if row is None:
            continue
        main_cum = main_yuan_from_wan(row.f_amo_sum_wan)
        main_delta = main_cum - previous_main_cum.get(sector_id, 0.0)
        records.append(
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id=sector_id,
                change_pct=change_pct_from_dqzf(row.dqzf),
                member_count=member_counts.get(sector_id, 0),
                funds=_official_funds(main_delta, main_cum),
                observed_at=observed_at,
                batch_id=batch_id,
            )
        )
    return records


def build_gap_stock_minutes(
    *,
    trade_date: date,
    minute: str,
    symbols: list[str],
    previous_main_cum: dict[str, float],
    observed_at: datetime,
    batch_id: str,
) -> list[StockMinute]:
    records: list[StockMinute] = []
    for symbol in sorted(symbols):
        cumulative = previous_main_cum.get(symbol, 0.0)
        records.append(
            StockMinute(
                trade_date=trade_date,
                minute=minute,
                symbol=symbol,
                close=0.0,
                change_pct=0.0,
                amount_delta=0.0,
                funds=_gap_funds(cumulative),
                observed_at=observed_at,
                batch_id=batch_id,
            )
        )
    return records


def build_gap_sector_minutes(
    *,
    trade_date: date,
    minute: str,
    sector_ids: list[str],
    member_counts: dict[str, int],
    previous_main_cum: dict[str, float],
    observed_at: datetime,
    batch_id: str,
) -> list[SectorMinute]:
    records: list[SectorMinute] = []
    for sector_id in sorted(sector_ids):
        cumulative = previous_main_cum.get(sector_id, 0.0)
        records.append(
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id=sector_id,
                change_pct=0.0,
                member_count=member_counts.get(sector_id, 0),
                funds=_gap_funds(cumulative),
                observed_at=observed_at,
                batch_id=batch_id,
            )
        )
    return records


def apply_written_main_cum(
    previous_main_cum: dict[str, float],
    records: list[StockMinute] | list[SectorMinute] | list,
    *,
    key_attr: str,
) -> None:
    for record in records:
        entity_id = getattr(record, key_attr)
        if record.funds.main.quality is DataQuality.GAP:
            continue
        previous_main_cum[str(entity_id)] = float(record.funds.main.cumulative)
