from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api.routes_auction_board import create_auction_board_router
from workbench.collector.trading_clock import auction_phase_at
from workbench.providers.eastmoney.auction_board import (
    EastMoneyAuctionBoardProvider,
    EastMoneyAuctionBoardRow,
)
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
        EastMoneyAuctionBoardRow(
            symbol="SZ000001",
            code="000001",
            name="平安银行",
            price=11.2,
            change_pct=-0.5,
            volume_ratio=0.8,
            amount=3_200_000.0,
            volume=2857.0,
            market=0,
        ),
    ]


def _service(tmp_path: Path) -> AuctionBoardService:
    provider = MagicMock()
    provider.fetch_rank.return_value = (_rows(), "eastmoney:auction:clist")
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


def _client(service: AuctionBoardService) -> TestClient:
    app = FastAPI()
    app.include_router(create_auction_board_router(service=service))
    return TestClient(app)


def test_auction_phase_windows() -> None:
    assert auction_phase_at(datetime(2026, 10, 7, 9, 10, tzinfo=SHANGHAI)) == "waiting"
    assert auction_phase_at(datetime(2026, 10, 7, 9, 18, tzinfo=SHANGHAI)) == "auction"
    assert auction_phase_at(datetime(2026, 10, 7, 9, 27, tzinfo=SHANGHAI)) == "post_auction"
    assert auction_phase_at(datetime(2026, 10, 7, 10, 0, tzinfo=SHANGHAI)) == "closed"


def test_build_board_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "workbench.services.auction_board.auction_phase_at",
        lambda: "auction",
    )
    monkeypatch.setattr(
        "workbench.services.auction_board.date",
        type("Date", (), {"today": staticmethod(lambda: date(2026, 10, 7))}),
    )
    service = _service(tmp_path)
    payload = service.board("2026-10-07", sort="ratio", force=True)

    assert payload.sort == "ratio"
    assert len(payload.items) == 2
    assert payload.items[0].name == "贵州茅台"
    assert payload.items[0].volume_ratio == 1.12
    assert payload.phase == "auction"


def test_historical_date_uses_snapshot_without_refetch(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.board("2026-09-30", sort="ratio", force=True)
    service._provider.fetch_all_market.reset_mock()

    second = service.board("2026-09-30", sort="ratio")
    assert second.data_kind == "snapshot"
    assert second.items[0].name == first.items[0].name
    service._provider.fetch_all_market.assert_not_called()


def test_darktrade_fallback_when_clist_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "workbench.services.auction_board.auction_phase_at",
        lambda: "auction",
    )
    monkeypatch.setattr(
        "workbench.services.auction_board.date",
        type("Date", (), {"today": staticmethod(lambda: date(2026, 10, 8))}),
    )
    provider = EastMoneyAuctionBoardProvider()
    monkeypatch.setattr(
        provider,
        "_fetch_clist_all_pages",
        lambda **_: (_ for _ in ()).throw(RuntimeError("clist blocked")),
    )
    monkeypatch.setattr(
        provider,
        "_fetch_darktrade_all_pages",
        lambda **_: _rows(),
    )
    gray_provider = MagicMock()
    snapshot_store = AuctionSnapshotStore(tmp_path / "auction_snapshots.sqlite")
    snapshot_store.initialize()
    service = AuctionBoardService(
        provider=provider,
        gray_provider=gray_provider,
        snapshot_store=snapshot_store,
        cache_ttl=10,
    )
    payload = service.board("2026-10-08", sort="ratio", force=True)
    assert payload.source == "eastmoney:auction:darktrade"
    assert len(payload.items) == 2


def test_today_closed_force_backfills_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "workbench.services.auction_board.auction_phase_at",
        lambda: "closed",
    )
    monkeypatch.setattr(
        "workbench.services.auction_board.date",
        type("Date", (), {"today": staticmethod(lambda: date(2026, 10, 7))}),
    )
    service = _service(tmp_path)
    empty = service.board("2026-10-07", sort="ratio")
    assert empty.items == []

    payload = service.board("2026-10-07", sort="ratio", force=True)
    assert len(payload.items) == 2
    assert payload.data_kind == "snapshot"

    cached = service.board("2026-10-07", sort="ratio")
    assert cached.data_kind == "snapshot"
    assert len(cached.items) == 2
    service._provider.fetch_all_market.assert_called_once()


def test_market_scope_search_and_pagination(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.board("2026-09-30", sort="ratio", force=True)

    matched = service.board("2026-09-30", sort="ratio", q="茅台", offset=0, limit=10)
    assert matched.total == 1
    assert matched.items[0].code == "600519"

    paged = service.board("2026-09-30", sort="ratio", offset=1, limit=1)
    assert paged.total == 2
    assert len(paged.items) == 1
    assert paged.items[0].rank == 2


def test_historical_top_reads_snapshot_not_live(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.board("2026-09-30", sort="ratio", scope="market", force=True)
    service._provider.fetch_rank.reset_mock()
    service._provider.fetch_all_market.reset_mock()

    payload = service.board("2026-09-30", sort="ratio", scope="top")
    assert payload.data_kind == "snapshot"
    assert payload.scope == "top"
    assert payload.total == 2
    service._provider.fetch_rank.assert_not_called()
    service._provider.fetch_all_market.assert_not_called()


def test_top_scope_uses_fetch_rank(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "workbench.services.auction_board.auction_phase_at",
        lambda: "auction",
    )
    monkeypatch.setattr(
        "workbench.services.auction_board.date",
        type("Date", (), {"today": staticmethod(lambda: date(2026, 10, 7))}),
    )
    service = _service(tmp_path)
    payload = service.board("2026-10-07", sort="ratio", scope="top", force=True)
    assert payload.scope == "top"
    assert payload.total == 2
    service._provider.fetch_rank.assert_called_once()
    service._provider.fetch_all_market.assert_not_called()


def test_api_auction_board(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "workbench.services.auction_board.auction_phase_at",
        lambda: "post_auction",
    )
    monkeypatch.setattr(
        "workbench.services.auction_board.date",
        type("Date", (), {"today": staticmethod(lambda: date(2026, 10, 7))}),
    )
    client = _client(_service(tmp_path))
    response = client.get(
        "/api/v1/market/auction-board",
        params={"trade_date": "2026-10-07", "sort": "amount"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "2026-10-07"
    assert payload["sort"] == "amount"
    assert payload["items"][0]["code"] == "600519"
