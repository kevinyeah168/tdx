from datetime import date, datetime, timezone

import pytest

from workbench.collector.sector_aggregator import SectorAggregator
from workbench.domain import DataQuality, FundFlow, Membership, StockMinute, TierPoint


def stock(
    symbol: str,
    *,
    change_pct: float = 0.0,
    main: tuple[float, float] = (0.0, 0.0),
    super_: tuple[float, float] = (0.0, 0.0),
    large: tuple[float, float] = (0.0, 0.0),
    medium: tuple[float, float] = (0.0, 0.0),
    small: tuple[float, float] = (0.0, 0.0),
    observed_at: datetime = datetime(2026, 8, 20, 9, 30, tzinfo=timezone.utc),
    trade_date: date = date(2026, 8, 20),
    minute: str = "09:30",
    batch_id: str = "batch-1",
) -> StockMinute:
    def tier(values: tuple[float, float]) -> TierPoint:
        return TierPoint(
            delta=values[0], cumulative=values[1], source="provider", quality=DataQuality.OFFICIAL
        )

    return StockMinute(
        trade_date=trade_date,
        minute=minute,
        symbol=symbol,
        close=10.0,
        change_pct=change_pct,
        amount_delta=100.0,
        funds=FundFlow(
            main=tier(main), super=tier(super_), large=tier(large), medium=tier(medium), small=tier(small)
        ),
        observed_at=observed_at,
        batch_id=batch_id,
    )


def test_aggregate_sums_each_tier_and_marks_result_aggregated() -> None:
    aggregator = SectorAggregator(
        [Membership(sector_id="881001", symbol="000001"), Membership(sector_id="881001", symbol="000002")]
    )

    result = aggregator.aggregate(
        [
            stock(
                "000001",
                change_pct=1.0,
                main=(140.0, 140.0),
                super_=(100.0, 100.0),
                large=(40.0, 40.0),
                medium=(5.0, 6.0),
                small=(7.0, 8.0),
            ),
            stock(
                "000002",
                change_pct=3.0,
                main=(-10.0, -10.0),
                super_=(-20.0, -20.0),
                large=(10.0, 10.0),
                medium=(9.0, 10.0),
                small=(11.0, 12.0),
            ),
        ]
    )

    assert len(result) == 1
    sector = result[0]
    assert sector.sector_id == "881001"
    assert sector.change_pct == 2.0
    assert sector.member_count == 2
    assert sector.funds.super.delta == 80.0
    assert sector.funds.super.cumulative == 80.0
    assert sector.funds.large.delta == 50.0
    assert sector.funds.large.cumulative == 50.0
    assert sector.funds.main.delta == 130.0
    assert sector.funds.medium.delta == 14.0
    assert sector.funds.medium.cumulative == 16.0
    assert sector.funds.small.delta == 18.0
    assert sector.funds.small.cumulative == 20.0
    for tier in (sector.funds.main, sector.funds.super, sector.funds.large, sector.funds.medium, sector.funds.small):
        assert tier.quality is DataQuality.AGGREGATED
        assert tier.source == "constituent_sum"


def test_aggregate_sums_main_independently_when_it_differs_from_super_plus_large() -> None:
    aggregator = SectorAggregator([Membership(sector_id="881001", symbol="000001")])

    result = aggregator.aggregate(
        [stock("000001", main=(99.0, 199.0), super_=(10.0, 20.0), large=(30.0, 40.0))]
    )

    assert result[0].funds.main.delta == 99.0
    assert result[0].funds.main.cumulative == 199.0


def test_aggregate_maps_stocks_to_multiple_sectors_sorts_output_and_uses_latest_observation() -> None:
    aggregator = SectorAggregator(
        [
            Membership(sector_id="881002", symbol="000001"),
            Membership(sector_id="881001", symbol="000001"),
        ]
    )
    latest = datetime(2026, 8, 20, 9, 31, tzinfo=timezone.utc)

    result = aggregator.aggregate([stock("000001", observed_at=latest)])

    assert [sector.sector_id for sector in result] == ["881001", "881002"]
    assert all(sector.observed_at == latest for sector in result)
    assert all(sector.trade_date == date(2026, 8, 20) for sector in result)
    assert all(sector.minute == "09:30" for sector in result)
    assert all(sector.batch_id == "batch-1" for sector in result)


def test_aggregate_ignores_unmapped_stocks_and_empty_input() -> None:
    aggregator = SectorAggregator([Membership(sector_id="881001", symbol="000001")])

    assert aggregator.aggregate([stock("999999")]) == []
    assert aggregator.aggregate([]) == []


def test_aggregate_deduplicates_duplicate_membership_pairs() -> None:
    aggregator = SectorAggregator(
        [
            Membership(sector_id="881001", symbol="000001"),
            Membership(sector_id="881001", symbol="000001"),
        ]
    )

    result = aggregator.aggregate([stock("000001", main=(9.0, 10.0))])

    assert result[0].member_count == 1
    assert result[0].funds.main.delta == 9.0
    assert result[0].funds.main.cumulative == 10.0


def test_aggregate_rejects_records_with_inconsistent_batch_identity() -> None:
    aggregator = SectorAggregator(
        [Membership(sector_id="881001", symbol="000001"), Membership(sector_id="881001", symbol="000002")]
    )

    with pytest.raises(ValueError, match="same trade_date, minute, and batch_id"):
        aggregator.aggregate([stock("000001"), stock("000002", batch_id="batch-2")])
