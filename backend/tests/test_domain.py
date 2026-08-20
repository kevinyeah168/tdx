from datetime import date, datetime

from workbench.domain import DataQuality, FundFlow, StockMinute


def test_estimated_main_equals_super_plus_large() -> None:
    funds = FundFlow.from_tiers(
        super_delta=30.0,
        super_cum=100.0,
        large_delta=-10.0,
        large_cum=40.0,
        medium_delta=5.0,
        medium_cum=20.0,
        small_delta=-2.0,
        small_cum=-5.0,
        source="pytdx_transactions",
        quality=DataQuality.ESTIMATED,
    )

    assert funds.main.delta == 20.0
    assert funds.main.cumulative == 140.0


def test_stock_minute_keeps_tier_provenance() -> None:
    record = StockMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        symbol="SH600000",
        close=10.2,
        change_pct=1.0,
        amount_delta=1_000_000.0,
        funds=FundFlow.zero("no_trade", DataQuality.OFFICIAL),
        observed_at=datetime(2026, 8, 20, 9, 31, 5),
        batch_id="2026-08-20T09:31",
    )

    assert record.funds.main.source == "no_trade"
    assert record.funds.super.quality is DataQuality.OFFICIAL
