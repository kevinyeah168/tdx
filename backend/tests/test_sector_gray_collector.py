from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from workbench.collector.gray_stock_collector import GrayStockCollector
from workbench.collector.sector_gray_aggregator import SectorGrayAggregator
from workbench.config import WorkbenchSettings
from workbench.domain import Membership
from workbench.providers.eastmoney.gray_market import GrayMarketProvider, StockGrayFlowSample
from workbench.storage.hot_store import HotStore


def _sample(symbol: str, code: str, dark: float) -> StockGrayFlowSample:
    return StockGrayFlowSample(
        trade_date="2026-09-11",
        symbol=symbol,
        code=code,
        stock_name=symbol,
        market="sh",
        open_net_inflow=1.0,
        dark_net_inflow=dark,
        total_net_inflow=dark + 1.0,
        sampled_at=datetime(2026, 9, 11, 10, 30, 45),
        source="test",
    )


def test_gray_collector_writes_sector_gray_from_memberships(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path)
    hot = HotStore(settings.hot_db_for("2026-09-11"))
    hot.initialize()
    provider = GrayMarketProvider()
    aggregator = SectorGrayAggregator(
        [
            Membership(sector_id="881001", symbol="SH600000"),
            Membership(sector_id="881001", symbol="SZ000001"),
        ]
    )
    collector = GrayStockCollector(
        hot,
        settings=settings,
        gray_provider=provider,
        sector_gray_aggregator=aggregator,
    )

    with patch.object(
        provider,
        "fetch_full_market_gray_snapshots",
        return_value=[
            _sample("SH600000", "600000", 10.0),
            _sample("SZ000001", "000001", 5.0),
        ],
    ):
        with patch(
            "workbench.collector.gray_stock_collector.datetime",
            wraps=datetime,
        ) as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 9, 11, 10, 30, 12)
            result = collector.collect(date(2026, 9, 11))

    assert result["gray_sectors"] == 1
    row = hot.connect(readonly=True).execute(
        "SELECT dark_cum, member_count, gray_covered_count, quality FROM sector_gray_minute "
        "WHERE sector_id=?",
        ("881001",),
    ).fetchone()
    assert row is not None
    assert row[0] == 15.0
    assert row[1] == 2
    assert row[2] == 2
    assert row[3] == "aggregated"
