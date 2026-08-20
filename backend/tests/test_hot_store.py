from datetime import date, datetime
from pathlib import Path

import sqlite3
from copy import deepcopy

import pytest

from workbench.domain import DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
from workbench.storage.hot_store import HotStore


def stock_record(close: float) -> StockMinute:
    return StockMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        symbol="SH600000",
        close=close,
        change_pct=1.0,
        amount_delta=1000.0,
        funds=FundFlow.from_tiers(
            super_delta=30.0,
            super_cum=100.0,
            large_delta=-10.0,
            large_cum=40.0,
            medium_delta=5.0,
            medium_cum=20.0,
            small_delta=-2.0,
            small_cum=-5.0,
            source="fake",
            quality=DataQuality.ESTIMATED,
        ),
        observed_at=datetime(2026, 8, 20, 9, 31, 5),
        batch_id="2026-08-20T09:31",
    )


def sector_record() -> SectorMinute:
    def tier(delta: float, cumulative: float, source: str) -> TierPoint:
        return TierPoint(
            delta=delta,
            cumulative=cumulative,
            source=source,
            quality=DataQuality.AGGREGATED,
        )

    return SectorMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        sector_id="881001",
        change_pct=1.5,
        member_count=2,
        funds=FundFlow(
            main=tier(99.0, 199.0, "main_sum"),
            super=tier(30.0, 100.0, "super_sum"),
            large=tier(10.0, 40.0, "large_sum"),
            medium=tier(5.0, 20.0, "medium_sum"),
            small=tier(-2.0, -5.0, "small_sum"),
        ),
        observed_at=datetime(2026, 8, 20, 9, 31, 5),
        batch_id="2026-08-20T09:31",
    )


def batch_status(*, status: str = "complete") -> dict[str, int | float | str]:
    return {
        "trade_date": "2026-08-20",
        "minute": "09:31",
        "batch_id": "2026-08-20T09:31",
        "expected_stocks": 1,
        "collected_stocks": 1,
        "expected_sectors": 1,
        "collected_sectors": 1,
        "duration_ms": 0,
        "coverage_pct": 100.0,
        "status": status,
        "error_summary": "",
    }


def test_stock_minute_upsert_is_idempotent(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    store.write_stocks([stock_record(10.0)])
    store.write_stocks([stock_record(10.2)])

    rows = store.stock_fund_series("2026-08-20", "SH600000")
    assert len(rows) == 1
    assert rows[0]["close"] == 10.2
    assert rows[0]["main_cum"] == 140.0
    assert rows[0]["super_cum"] == 100.0
    assert rows[0]["large_cum"] == 40.0


def test_uncommitted_minute_is_not_reported_complete(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    store.write_stocks([stock_record(10.0)])

    assert store.latest_complete_minute("2026-08-20") is None


def test_complete_batch_round_trips_sector_tiers_and_provenance(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()

    store.write_complete_batch(
        [stock_record(10.0)], [sector_record()], batch_status(), started_at=0.0
    )

    rows = store.sector_fund_series("2026-08-20", "881001")
    assert len(rows) == 1
    assert rows[0]["main_delta"] == 99.0
    assert rows[0]["super_cum"] == 100.0
    assert rows[0]["large_cum"] == 40.0
    assert rows[0]["tier_meta"] == {
        "main": {"source": "main_sum", "quality": "aggregated"},
        "super": {"source": "super_sum", "quality": "aggregated"},
        "large": {"source": "large_sum", "quality": "aggregated"},
        "medium": {"source": "medium_sum", "quality": "aggregated"},
        "small": {"source": "small_sum", "quality": "aggregated"},
    }


def test_complete_batch_rolls_back_all_rows_when_status_insert_fails(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    status = batch_status()
    status["status"] = None  # type: ignore[assignment]

    with pytest.raises(sqlite3.IntegrityError):
        store.write_complete_batch([stock_record(10.0)], [sector_record()], status, started_at=0.0)

    assert store.stock_fund_series("2026-08-20", "SH600000") == []
    assert store.sector_fund_series("2026-08-20", "881001") == []
    assert store.latest_complete_minute("2026-08-20") is None


def test_complete_batch_is_idempotent_and_does_not_mutate_status(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    status = batch_status()
    original = deepcopy(status)

    store.write_complete_batch([stock_record(10.0)], [sector_record()], status, started_at=0.0)
    store.write_complete_batch([stock_record(10.2)], [sector_record()], status, started_at=0.0)

    assert status == original
    assert len(store.stock_fund_series("2026-08-20", "SH600000")) == 1
    assert len(store.sector_fund_series("2026-08-20", "881001")) == 1


def test_readonly_connect_does_not_create_parent_directories(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing" / "hot.sqlite"

    with pytest.raises(sqlite3.OperationalError):
        HotStore(missing_path).connect(readonly=True)

    assert not missing_path.parent.exists()
