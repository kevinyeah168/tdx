from datetime import date, datetime
from pathlib import Path

from workbench.domain import DataQuality, FundFlow, StockMinute
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
