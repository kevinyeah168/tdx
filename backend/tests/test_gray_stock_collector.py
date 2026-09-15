from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from workbench.collector.gray_stock_collector import GrayStockCollector
from workbench.config import WorkbenchSettings
from workbench.providers.eastmoney.gray_market import GrayMarketProvider, StockGrayFlowSample
from workbench.storage.hot_store import HotStore


def _sample(symbol: str, code: str) -> StockGrayFlowSample:
    return StockGrayFlowSample(
        trade_date="2026-09-11",
        symbol=symbol,
        code=code,
        stock_name=symbol,
        market="sh",
        open_net_inflow=1.0,
        dark_net_inflow=2.0,
        total_net_inflow=3.0,
        sampled_at=datetime(2026, 9, 11, 10, 30, 45),
        source="test",
    )


def test_gray_collector_upserts_same_wall_clock_minute(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path)
    hot = HotStore(settings.hot_db_for("2026-09-11"))
    hot.initialize()
    provider = GrayMarketProvider()
    collector = GrayStockCollector(hot, settings=settings, gray_provider=provider)

    with patch.object(
        provider,
        "fetch_full_market_gray_snapshots",
        return_value=[_sample("SH600000", "600000")],
    ):
        with patch(
            "workbench.collector.gray_stock_collector.datetime",
            wraps=datetime,
        ) as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 9, 11, 10, 30, 12)
            first = collector.collect(date(2026, 9, 11), "10:29")
            mock_datetime.now.return_value = datetime(2026, 9, 11, 10, 30, 48)
            second = collector.collect(date(2026, 9, 11), "10:29")

    assert first["minute"] == "10:30"
    assert second["minute"] == "10:30"
    rows = hot.connect(readonly=True).execute(
        "SELECT minute, dark_cum, observed_at FROM stock_gray_minute WHERE symbol=?",
        ("SH600000",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "10:30"
    assert rows[0][1] == 2.0


def test_gray_collector_starts_new_minute_after_rollover(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path)
    hot = HotStore(settings.hot_db_for("2026-09-11"))
    hot.initialize()
    provider = GrayMarketProvider()
    collector = GrayStockCollector(hot, settings=settings, gray_provider=provider)

    with patch.object(
        provider,
        "fetch_full_market_gray_snapshots",
        side_effect=[
            [_sample("SH600000", "600000")],
            [_sample("SH600000", "600000")],
        ],
    ):
        with patch(
            "workbench.collector.gray_stock_collector.datetime",
            wraps=datetime,
        ) as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 9, 11, 10, 30, 50)
            collector.collect(date(2026, 9, 11))
            mock_datetime.now.return_value = datetime(2026, 9, 11, 10, 31, 5)
            result = collector.collect(date(2026, 9, 11))

    assert result["minute"] == "10:31"
    rows = hot.connect(readonly=True).execute(
        "SELECT minute FROM stock_gray_minute WHERE symbol=? ORDER BY minute",
        ("SH600000",),
    ).fetchall()
    assert [row[0] for row in rows] == ["10:30", "10:31"]
