from __future__ import annotations

from datetime import date, datetime

from workbench.collector.sector_gray_aggregator import SECTOR_GRAY_SOURCE, SectorGrayAggregator
from workbench.domain import DataQuality, Membership, StockGrayMinute


def _gray(symbol: str, dark: float, open_cum: float = 1.0) -> StockGrayMinute:
    return StockGrayMinute(
        trade_date=date(2026, 9, 11),
        minute="10:30",
        symbol=symbol,
        code=symbol[-6:],
        open_cum=open_cum,
        dark_cum=dark,
        total_cum=open_cum + dark,
        observed_at=datetime(2026, 9, 11, 10, 30),
        batch_id="test-gray",
        source="eastmoney:graymarket:darktrade",
    )


def test_sector_gray_aggregator_sums_constituents() -> None:
    aggregator = SectorGrayAggregator(
        [
            Membership(sector_id="881001", symbol="SH600000"),
            Membership(sector_id="881001", symbol="SZ000001"),
            Membership(sector_id="881002", symbol="SZ000001"),
        ]
    )
    records = aggregator.aggregate(
        [_gray("SH600000", 10.0), _gray("SZ000001", 5.0, open_cum=2.0)],
        trade_date=date(2026, 9, 11),
        minute="10:30",
        observed_at=datetime(2026, 9, 11, 10, 30),
        batch_id="test-gray",
    )

    by_sector = {record.sector_id: record for record in records}
    assert set(by_sector) == {"881001", "881002"}
    assert by_sector["881001"].dark_cum == 15.0
    assert by_sector["881001"].open_cum == 3.0
    assert by_sector["881001"].member_count == 2
    assert by_sector["881001"].gray_covered_count == 2
    assert by_sector["881002"].dark_cum == 5.0
    assert by_sector["881002"].member_count == 1
    assert by_sector["881001"].source == SECTOR_GRAY_SOURCE
    assert by_sector["881001"].quality is DataQuality.AGGREGATED


def test_sector_gray_aggregator_skips_sectors_without_coverage() -> None:
    aggregator = SectorGrayAggregator([Membership(sector_id="881001", symbol="SH600000")])
    records = aggregator.aggregate(
        [],
        trade_date=date(2026, 9, 11),
        minute="10:30",
        observed_at=datetime(2026, 9, 11, 10, 30),
        batch_id="test-gray",
    )
    assert records == []
