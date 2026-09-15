from __future__ import annotations

from datetime import date, datetime

from workbench.domain import DataQuality
from workbench.providers.tdx.yuntu_minute_records import (
    GAP_SOURCE,
    YUNTU_SOURCE,
    build_gap_sector_minutes,
    build_gap_stock_minutes,
    build_sector_minutes_from_yuntu,
    build_stock_minutes_from_yuntu,
)
from workbench.providers.tdx.yuntu_sector_flow import YuntuStockQuote


def test_build_stock_minutes_from_yuntu_maps_code_and_delta() -> None:
    rows = [
        YuntuStockQuote(
            stockcode="600519",
            setcode=1,
            dqzf=0.01,
            f_amo_sum_wan=-100.0,
            now=100.0,
            z_close=99.0,
        )
    ]
    records = build_stock_minutes_from_yuntu(
        trade_date=date(2026, 9, 14),
        minute="09:31",
        rows=rows,
        code_to_symbol={"600519": "SH600519"},
        previous_main_cum={"SH600519": -500_000.0},
        observed_at=datetime(2026, 9, 14, 9, 31),
        batch_id="2026-09-14T09:31-yuntu",
    )
    assert len(records) == 1
    record = records[0]
    assert record.symbol == "SH600519"
    assert record.funds.main.source == YUNTU_SOURCE
    assert record.funds.main.cumulative == -1_000_000.0
    assert record.funds.main.delta == -500_000.0
    assert record.change_pct == 1.0


def test_build_gap_stock_minutes_marks_gap_source() -> None:
    records = build_gap_stock_minutes(
        trade_date=date(2026, 9, 14),
        minute="09:32",
        symbols=["SH600519"],
        previous_main_cum={"SH600519": 1_000_000.0},
        observed_at=datetime(2026, 9, 14, 9, 32),
        batch_id="2026-09-14T09:32-yuntu-gap",
    )
    record = records[0]
    assert record.funds.main.source == GAP_SOURCE
    assert record.funds.main.quality is DataQuality.GAP
    assert record.funds.main.cumulative == 1_000_000.0
    assert record.funds.main.delta == 0.0


def test_build_sector_minutes_from_yuntu_ignores_missing_sector() -> None:
    rows = [
        YuntuStockQuote(
            stockcode="880656",
            setcode=1,
            dqzf=-0.012,
            f_amo_sum_wan=-4700.0,
            now=0.0,
            z_close=0.0,
        )
    ]
    records = build_sector_minutes_from_yuntu(
        trade_date=date(2026, 9, 14),
        minute="09:31",
        rows=rows,
        sector_ids=["880656", "880550"],
        member_counts={"880656": 42, "880550": 10},
        previous_main_cum={},
        observed_at=datetime(2026, 9, 14, 9, 31),
        batch_id="2026-09-14T09:31-yuntu",
    )
    assert [record.sector_id for record in records] == ["880656"]
    assert records[0].member_count == 42


def test_build_gap_sector_minutes_writes_all_sectors() -> None:
    records = build_gap_sector_minutes(
        trade_date=date(2026, 9, 14),
        minute="09:33",
        sector_ids=["880656", "880550"],
        member_counts={"880656": 1, "880550": 2},
        previous_main_cum={"880656": 10.0},
        observed_at=datetime(2026, 9, 14, 9, 33),
        batch_id="2026-09-14T09:33-yuntu-gap",
    )
    assert len(records) == 2
    assert all(record.funds.main.quality is DataQuality.GAP for record in records)
