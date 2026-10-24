from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from workbench.collector.auction_snapshot_collector import AuctionSnapshotCollector
from workbench.config import WorkbenchSettings
from workbench.providers.eastmoney.auction_board import EastMoneyAuctionBoardRow
from workbench.services.auction_board import AuctionBoardService
from workbench.storage.auction_snapshot_store import AuctionSnapshotStore

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _rows() -> list[EastMoneyAuctionBoardRow]:
    return [
        EastMoneyAuctionBoardRow(
            symbol="SH600519",
            code="600519",
            name="贵州茅台",
            price=1421.0,
            change_pct=0.35,
            volume_ratio=1.12,
            amount=17_904_600.0,
            volume=126.0,
            market=1,
        ),
    ]


def _service(tmp_path: Path) -> AuctionBoardService:
    provider = MagicMock()
    provider.fetch_all_market.return_value = (_rows(), "eastmoney:auction:clist")
    gray_provider = MagicMock()
    gray_provider.fetch_full_market_gray_snapshots.return_value = []
    snapshot_store = AuctionSnapshotStore(tmp_path / "auction_snapshots.sqlite")
    snapshot_store.initialize()
    return AuctionBoardService(
        provider=provider,
        gray_provider=gray_provider,
        snapshot_store=snapshot_store,
        cache_ttl=10,
    )


def test_collect_if_due_skips_outside_post_auction_window(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path)
    collector = AuctionSnapshotCollector(settings, service=_service(tmp_path))
    now = datetime(2026, 10, 7, 10, 0, tzinfo=SHANGHAI)

    assert collector.collect_if_due(date(2026, 10, 7), now) is None


def test_collect_if_due_persists_full_market_at_scheduled_minute(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path)
    service = _service(tmp_path)
    collector = AuctionSnapshotCollector(settings, service=service)
    trade_date = date(2026, 10, 7)
    now = datetime(2026, 10, 7, 9, 26, tzinfo=SHANGHAI)

    result = collector.collect_if_due(trade_date, now)

    assert result is not None
    assert result["mode"] == "auction-snapshot"
    assert result["minute"] == "09:26"
    assert result["total"] == 1
    snapshot = service.board("2026-10-07", sort="ratio")
    assert snapshot.data_kind == "snapshot"
    assert snapshot.total == 1
    assert len(snapshot.items) == 1


def test_collect_if_due_runs_once_per_minute(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path)
    service = _service(tmp_path)
    collector = AuctionSnapshotCollector(settings, service=service)
    trade_date = date(2026, 10, 7)
    now = datetime(2026, 10, 7, 9, 29, tzinfo=SHANGHAI)

    assert collector.collect_if_due(trade_date, now) is not None
    assert collector.collect_if_due(trade_date, now) is None
    assert service._provider.fetch_all_market.call_count == 1
