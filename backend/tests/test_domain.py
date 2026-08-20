from datetime import date, datetime
from math import inf, nan
from typing import Callable

import pytest
from pydantic import ValidationError

from workbench.domain import (
    DataQuality,
    FundFlow,
    Membership,
    ProviderMinuteBatch,
    Security,
    Sector,
    SectorMinute,
    StockMinute,
    TierPoint,
)


def stock_minute(**overrides: object) -> StockMinute:
    values: dict[str, object] = {
        "trade_date": date(2026, 8, 20),
        "minute": "09:31",
        "symbol": "SH600000",
        "close": 10.2,
        "change_pct": 1.0,
        "amount_delta": 1_000_000.0,
        "funds": FundFlow.zero("no_trade", DataQuality.OFFICIAL),
        "observed_at": datetime(2026, 8, 20, 9, 31, 5),
        "batch_id": "2026-08-20T09:31",
    }
    values.update(overrides)
    return StockMinute(**values)


def sector_minute(**overrides: object) -> SectorMinute:
    values: dict[str, object] = {
        "trade_date": date(2026, 8, 20),
        "minute": "09:31",
        "sector_id": "BK0001",
        "change_pct": 1.0,
        "member_count": 2,
        "funds": FundFlow.zero("no_trade", DataQuality.OFFICIAL),
        "observed_at": datetime(2026, 8, 20, 9, 31, 5),
        "batch_id": "2026-08-20T09:31",
    }
    values.update(overrides)
    return SectorMinute(**values)


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


@pytest.mark.parametrize("value", [nan, inf, -inf])
@pytest.mark.parametrize(
    "factory",
    [
        lambda value: TierPoint(delta=value, source="source", quality=DataQuality.OFFICIAL),
        lambda value: TierPoint(cumulative=value, source="source", quality=DataQuality.OFFICIAL),
        lambda value: stock_minute(close=value),
        lambda value: stock_minute(change_pct=value),
        lambda value: stock_minute(amount_delta=value),
        lambda value: sector_minute(change_pct=value),
    ],
)
def test_market_float_fields_reject_nonfinite_values(
    factory: Callable[[float], object], value: float
) -> None:
    with pytest.raises(ValidationError):
        factory(value)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: stock_minute(close=-0.01),
        lambda: stock_minute(amount_delta=-0.01),
        lambda: sector_minute(member_count=-1),
        lambda: ProviderMinuteBatch(
            trade_date=date(2026, 8, 20),
            minute="09:31",
            stocks=[],
            expected_stocks=-1,
        ),
    ],
)
def test_nonnegative_market_fields_reject_negative_values(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: stock_minute(minute="99:99"),
        lambda: sector_minute(minute="99:99"),
        lambda: ProviderMinuteBatch(
            trade_date=date(2026, 8, 20),
            minute="99:99",
            stocks=[],
            expected_stocks=0,
        ),
    ],
)
def test_minute_fields_reject_invalid_clock_times(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_provider_batch_rejects_expected_stock_count_below_records() -> None:
    with pytest.raises(ValidationError):
        ProviderMinuteBatch(
            trade_date=date(2026, 8, 20),
            minute="09:31",
            stocks=[stock_minute()],
            expected_stocks=0,
        )


def test_provider_batch_rejects_duplicate_symbols() -> None:
    with pytest.raises(ValidationError):
        ProviderMinuteBatch(
            trade_date=date(2026, 8, 20),
            minute="09:31",
            stocks=[stock_minute(), stock_minute()],
            expected_stocks=2,
        )


@pytest.mark.parametrize(
    "stock",
    [
        stock_minute(trade_date=date(2026, 8, 19)),
        stock_minute(minute="09:32"),
    ],
)
def test_provider_batch_rejects_stocks_outside_its_time_bucket(stock: StockMinute) -> None:
    with pytest.raises(ValidationError):
        ProviderMinuteBatch(
            trade_date=date(2026, 8, 20),
            minute="09:31",
            stocks=[stock],
            expected_stocks=1,
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TierPoint(source="source", quality=DataQuality.OFFICIAL, unknown=True),
        lambda: FundFlow(
            main=FundFlow.zero("source", DataQuality.OFFICIAL).main,
            super=FundFlow.zero("source", DataQuality.OFFICIAL).super,
            large=FundFlow.zero("source", DataQuality.OFFICIAL).large,
            medium=FundFlow.zero("source", DataQuality.OFFICIAL).medium,
            small=FundFlow.zero("source", DataQuality.OFFICIAL).small,
            unknown=True,
        ),
        lambda: Security(
            symbol="SH600000",
            code="600000",
            name="浦发银行",
            market="SH",
            unknown=True,
        ),
        lambda: Sector(sector_id="BK0001", name="银行", sector_type="industry", unknown=True),
        lambda: Membership(sector_id="BK0001", symbol="SH600000", unknown=True),
        lambda: stock_minute(unknown=True),
        lambda: sector_minute(unknown=True),
        lambda: ProviderMinuteBatch(
            trade_date=date(2026, 8, 20),
            minute="09:31",
            stocks=[],
            expected_stocks=0,
            unknown=True,
        ),
    ],
)
def test_domain_models_forbid_unknown_fields(factory: Callable[[], object]) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_fund_flow_allows_official_main_to_diverge_from_estimated_subtiers() -> None:
    funds = FundFlow(
        main=TierPoint(
            delta=100.0,
            cumulative=500.0,
            source="official_provider",
            quality=DataQuality.OFFICIAL,
        ),
        super=TierPoint(
            delta=30.0,
            cumulative=120.0,
            source="estimated_provider",
            quality=DataQuality.ESTIMATED,
        ),
        large=TierPoint(
            delta=20.0,
            cumulative=80.0,
            source="estimated_provider",
            quality=DataQuality.ESTIMATED,
        ),
        medium=TierPoint(
            source="estimated_provider",
            quality=DataQuality.ESTIMATED,
        ),
        small=TierPoint(
            source="estimated_provider",
            quality=DataQuality.ESTIMATED,
        ),
    )

    assert funds.main.delta == 100.0
    assert funds.main.delta != funds.super.delta + funds.large.delta
    assert funds.main.quality is DataQuality.OFFICIAL
