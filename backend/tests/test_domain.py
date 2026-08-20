from datetime import date, datetime
from math import inf, nan
from typing import Callable

import pytest
from pydantic import ValidationError

from workbench.domain import (
    Bar,
    CollectionStatus,
    DataEnvelope,
    DataQuality,
    FundFlow,
    Membership,
    OrderBook,
    OrderBookLevel,
    ProviderCapabilities,
    ProviderMinuteBatch,
    QuoteSnapshot,
    Security,
    Sector,
    SectorMinute,
    StockMinute,
    TierPoint,
    Transaction,
)


def quote_snapshot(**overrides: object) -> QuoteSnapshot:
    values: dict[str, object] = {
        "symbol": "SH600000",
        "trade_date": date(2026, 8, 20),
        "minute": "09:31",
        "price": 10.2,
        "previous_close": 10.0,
        "change_pct": 2.0,
        "volume": 12_000.0,
        "amount": 1_224_000.0,
    }
    values.update(overrides)
    return QuoteSnapshot(**values)


def order_book_levels(prices: list[float]) -> list[OrderBookLevel]:
    return [
        OrderBookLevel(price=price, volume=float(1_000 * (index + 1)))
        for index, price in enumerate(prices)
    ]


def order_book(**overrides: object) -> OrderBook:
    values: dict[str, object] = {
        "symbol": "SH600000",
        "trade_date": date(2026, 8, 20),
        "minute": "09:31",
        "bids": order_book_levels([10.00, 9.99, 9.98, 9.97, 9.96]),
        "asks": order_book_levels([10.01, 10.02, 10.03, 10.04, 10.05]),
    }
    values.update(overrides)
    return OrderBook(**values)


def bar(**overrides: object) -> Bar:
    values: dict[str, object] = {
        "symbol": "SH600000",
        "period": "1d",
        "timestamp": datetime(2026, 8, 20, 15, 0),
        "open": 10.0,
        "high": 10.8,
        "low": 9.8,
        "close": 10.2,
        "volume": 12_000.0,
        "amount": 1_224_000.0,
    }
    values.update(overrides)
    return Bar(**values)


def transaction(**overrides: object) -> Transaction:
    values: dict[str, object] = {
        "symbol": "SH600000",
        "trade_date": date(2026, 8, 20),
        "timestamp": datetime(2026, 8, 20, 9, 31, 5),
        "price": 10.2,
        "volume": 1_000.0,
        "amount": 10_200.0,
        "side": "buy",
    }
    values.update(overrides)
    return Transaction(**values)


def provider_capabilities(**overrides: object) -> ProviderCapabilities:
    values: dict[str, object] = {
        "catalog": True,
        "minute": True,
        "quote": True,
        "transaction": True,
        "bars": True,
        "order_book": True,
    }
    values.update(overrides)
    return ProviderCapabilities(**values)


def data_envelope(**overrides: object) -> DataEnvelope[dict[str, str]]:
    values: dict[str, object] = {
        "data": {"symbol": "SH600000"},
        "source": "pytdx_quotes",
        "quality": DataQuality.OFFICIAL,
        "observed_at": datetime(2026, 8, 20, 9, 31, 5),
        "catalog_version": "catalog-v1",
    }
    values.update(overrides)
    return DataEnvelope[dict[str, str]](**values)


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


def collection_status(**overrides: object) -> CollectionStatus:
    values: dict[str, object] = {
        "trade_date": date(2026, 8, 20),
        "minute": "09:31",
        "batch_id": "2026-08-20T09:31",
        "catalog_version": "catalog-v1",
        "expected_stocks": 100,
        "collected_stocks": 100,
        "expected_sectors": 4,
        "collected_sectors": 4,
        "duration_ms": 1,
        "coverage_pct": 100.0,
        "status": "complete",
        "error_summary": "",
    }
    values.update(overrides)
    return CollectionStatus(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"catalog_version": "  "},
        {"collected_stocks": 101},
        {"collected_sectors": 5},
        {"coverage_pct": 99.0},
        {"status": "unknown"},
        {"status": "complete", "collected_sectors": 3},
    ],
)
def test_collection_status_rejects_invalid_or_inconsistent_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        collection_status(**overrides)


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


@pytest.mark.parametrize("value", ["", " \t "])
@pytest.mark.parametrize(
    "factory",
    [
        lambda value: TierPoint(source=value, quality=DataQuality.OFFICIAL),
        lambda value: Security(symbol=value, code="600000", name="Bank", market="SH"),
        lambda value: Security(symbol="SH600000", code=value, name="Bank", market="SH"),
        lambda value: Security(symbol="SH600000", code="600000", name=value, market="SH"),
        lambda value: Security(symbol="SH600000", code="600000", name="Bank", market=value),
        lambda value: Sector(sector_id=value, name="Bank", sector_type="industry"),
        lambda value: Sector(sector_id="BK0001", name=value, sector_type="industry"),
        lambda value: Sector(sector_id="BK0001", name="Bank", sector_type=value),
        lambda value: Membership(sector_id=value, symbol="SH600000"),
        lambda value: Membership(sector_id="BK0001", symbol=value),
        lambda value: stock_minute(symbol=value),
        lambda value: stock_minute(batch_id=value),
        lambda value: sector_minute(sector_id=value),
        lambda value: sector_minute(batch_id=value),
    ],
)
def test_required_identifier_fields_reject_blank_text(
    factory: Callable[[str], object], value: str
) -> None:
    with pytest.raises(ValidationError):
        factory(value)


@pytest.mark.parametrize(
    "factory",
    [
        lambda value: TierPoint(source=value, quality=DataQuality.OFFICIAL).source,
        lambda value: Security(symbol=value, code="600000", name="Bank", market="SH").symbol,
        lambda value: Security(symbol="SH600000", code=value, name="Bank", market="SH").code,
        lambda value: Security(symbol="SH600000", code="600000", name=value, market="SH").name,
        lambda value: Security(symbol="SH600000", code="600000", name="Bank", market=value).market,
        lambda value: Sector(sector_id=value, name="Bank", sector_type="industry").sector_id,
        lambda value: Sector(sector_id="BK0001", name=value, sector_type="industry").name,
        lambda value: Sector(sector_id="BK0001", name="Bank", sector_type=value).sector_type,
        lambda value: Membership(sector_id=value, symbol="SH600000").sector_id,
        lambda value: Membership(sector_id="BK0001", symbol=value).symbol,
        lambda value: stock_minute(symbol=value).symbol,
        lambda value: stock_minute(batch_id=value).batch_id,
        lambda value: sector_minute(sector_id=value).sector_id,
        lambda value: sector_minute(batch_id=value).batch_id,
    ],
)
def test_required_identifier_fields_strip_surrounding_whitespace(
    factory: Callable[[str], str],
) -> None:
    assert factory("  identifier\t") == "identifier"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: quote_snapshot(unknown=True),
        lambda: order_book(unknown=True),
        lambda: bar(unknown=True),
        lambda: transaction(unknown=True),
        lambda: provider_capabilities(unknown=True),
        lambda: data_envelope(unknown=True),
    ],
)
def test_real_provider_domain_models_forbid_unknown_fields(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: quote_snapshot(trade_date="2026-08-20"),
        lambda: quote_snapshot(price="10.2"),
        lambda: provider_capabilities(catalog=1),
        lambda: data_envelope(quality="official"),
        lambda: data_envelope(observed_at="2026-08-20T09:31:05"),
    ],
)
def test_real_provider_domain_models_reject_coercible_wrong_types(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        factory()


@pytest.mark.parametrize("symbol", ["600000", "XX600000", "SH60000", "sh600000"])
@pytest.mark.parametrize(
    "factory",
    [quote_snapshot, order_book, bar, transaction],
)
def test_real_market_records_require_market_prefixed_symbols(
    factory: Callable[..., object], symbol: str
) -> None:
    with pytest.raises(ValidationError):
        factory(symbol=symbol)


@pytest.mark.parametrize(
    "factory",
    [quote_snapshot, order_book],
)
def test_real_market_minutes_reject_invalid_clock_times(
    factory: Callable[..., object],
) -> None:
    with pytest.raises(ValidationError):
        factory(minute="24:00")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: bar(timestamp="not-a-timestamp"),
        lambda: transaction(timestamp="not-a-timestamp"),
        lambda: data_envelope(observed_at="not-a-timestamp"),
    ],
)
def test_real_market_timestamps_must_be_valid(factory: Callable[[], object]) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_transaction_timestamp_must_match_trade_date() -> None:
    with pytest.raises(ValidationError):
        transaction(timestamp=datetime(2026, 8, 19, 15, 0))


@pytest.mark.parametrize("value", [nan, inf, -inf])
@pytest.mark.parametrize(
    "factory",
    [
        lambda value: quote_snapshot(price=value),
        lambda value: quote_snapshot(previous_close=value),
        lambda value: quote_snapshot(change_pct=value),
        lambda value: quote_snapshot(volume=value),
        lambda value: quote_snapshot(amount=value),
        lambda value: OrderBookLevel(price=value, volume=1.0),
        lambda value: OrderBookLevel(price=1.0, volume=value),
        lambda value: bar(open=value),
        lambda value: bar(high=value),
        lambda value: bar(low=value),
        lambda value: bar(close=value),
        lambda value: bar(volume=value),
        lambda value: bar(amount=value),
        lambda value: transaction(price=value),
        lambda value: transaction(volume=value),
        lambda value: transaction(amount=value),
    ],
)
def test_real_market_numeric_fields_reject_nonfinite_values(
    factory: Callable[[float], object], value: float
) -> None:
    with pytest.raises(ValidationError):
        factory(value)


@pytest.mark.parametrize(
    "side",
    ["buyer", "seller", "unknown"],
)
def test_transaction_rejects_unknown_trade_sides(side: str) -> None:
    with pytest.raises(ValidationError):
        transaction(side=side)


@pytest.mark.parametrize("side", ["buy", "sell", "neutral"])
def test_transaction_accepts_normalized_trade_sides(side: str) -> None:
    assert transaction(side=side).side == side


@pytest.mark.parametrize(
    "overrides",
    [
        {"bids": order_book_levels([10.00, 9.99, 9.98, 9.97])},
        {"asks": order_book_levels([10.01, 10.02, 10.03, 10.04, 10.05, 10.06])},
        {"bids": order_book_levels([10.00, 9.99, 10.01, 9.97, 9.96])},
        {"asks": order_book_levels([10.01, 10.02, 10.00, 10.04, 10.05])},
        {"bids": order_book_levels([10.00, 9.99, 9.99, 9.97, 9.96])},
        {"asks": order_book_levels([10.01, 10.02, 10.02, 10.04, 10.05])},
    ],
)
def test_order_book_requires_five_price_ordered_levels(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        order_book(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"high": 9.99},
        {"high": 10.1, "close": 10.2},
        {"low": 10.01},
        {"low": 9.9, "close": 9.8},
    ],
)
def test_bar_rejects_inconsistent_ohlc_relationships(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        bar(**overrides)


def test_data_envelope_preserves_provenance_and_optional_gap_reason() -> None:
    observed_at = datetime(2026, 8, 20, 9, 31, 5)
    envelope = data_envelope(
        source=" enhanced_quotes ",
        quality=DataQuality.GAP,
        observed_at=observed_at,
        catalog_version=" catalog-v2 ",
        gap_reason=" quote fields unavailable ",
    )

    assert envelope.data == {"symbol": "SH600000"}
    assert envelope.source == "enhanced_quotes"
    assert envelope.quality is DataQuality.GAP
    assert envelope.observed_at == observed_at
    assert envelope.catalog_version == "catalog-v2"
    assert envelope.gap_reason == "quote fields unavailable"
    assert data_envelope().gap_reason is None
