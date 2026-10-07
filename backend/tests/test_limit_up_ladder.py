from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api.routes_limit_up import create_limit_up_router
from workbench.providers.eastmoney.limit_up import EastMoneyLimitUpRow
from workbench.services.limit_up_ladder import LimitUpLadderService
from workbench.storage.limit_up_snapshot_store import LimitUpSnapshotStore


def _rows() -> list[EastMoneyLimitUpRow]:
    return [
        EastMoneyLimitUpRow(
            symbol="SH600825",
            code="600825",
            name="新华传媒",
            price=103.5,
            change_pct=9.99,
            board_days=7,
            first_seal_time="09:25",
            last_seal_time="09:25",
            seal_amount=1_988_381_638,
            broken_count=0,
            industry="出版",
            turnover_rate=1.33,
            limit_stats="7天7板",
        ),
        EastMoneyLimitUpRow(
            symbol="SZ000011",
            code="000011",
            name="深物业A",
            price=12.24,
            change_pct=9.97,
            board_days=3,
            first_seal_time="09:31",
            last_seal_time="13:11",
            seal_amount=40_166_967,
            broken_count=2,
            industry="房地产",
            turnover_rate=17.07,
            limit_stats="3天3板",
        ),
        EastMoneyLimitUpRow(
            symbol="SZ000504",
            code="000504",
            name="南华生物",
            price=10.2,
            change_pct=10.0,
            board_days=1,
            first_seal_time="10:22",
            last_seal_time="10:22",
            seal_amount=12_000_000,
            broken_count=0,
            industry="医药",
            turnover_rate=8.1,
            limit_stats="1天1板",
        ),
    ]


def _service(tmp_path: Path) -> LimitUpLadderService:
    provider = MagicMock()
    provider.fetch_limit_up_pool.return_value = _rows()
    provider.fetch_broken_pool.return_value = [
        EastMoneyLimitUpRow(
            symbol="SZ002262",
            code="002262",
            name="恩华药业",
            price=22.73,
            change_pct=5.72,
            board_days=0,
            first_seal_time="09:25",
            last_seal_time=None,
            seal_amount=None,
            broken_count=1,
            industry="化学制药",
            turnover_rate=3.29,
            limit_stats=None,
        )
    ]
    snapshot_store = LimitUpSnapshotStore(tmp_path / "limit_up_snapshots.sqlite")
    snapshot_store.initialize()
    return LimitUpLadderService(provider=provider, snapshot_store=snapshot_store, cache_ttl=60)


def _client(service: LimitUpLadderService) -> TestClient:
    app = FastAPI()
    app.include_router(create_limit_up_router(service=service))
    return TestClient(app)


def test_build_tiers_sorted_by_board_days(tmp_path: Path) -> None:
    service = _service(tmp_path)
    payload = service.ladder("2026-09-30", force=True)

    assert payload.summary.limit_up_count == 3
    assert payload.summary.max_board == 7
    assert payload.summary.broken_count == 1
    assert payload.summary.first_board_count == 1
    assert payload.summary.multi_board_count == 2
    assert [tier.board_days for tier in payload.tiers] == [7, 3, 1]
    assert payload.tiers[0].label == "7板及以上"
    assert payload.tiers[0].items[0].name == "新华传媒"


def test_historical_date_uses_snapshot_without_refetch(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.ladder("2026-09-30", force=True)
    service._provider.fetch_limit_up_pool.reset_mock()
    service._provider.fetch_broken_pool.reset_mock()

    second = service.ladder("2026-09-30")
    assert second.data_kind == "snapshot"
    assert second.summary.limit_up_count == first.summary.limit_up_count
    service._provider.fetch_limit_up_pool.assert_not_called()
    service._provider.fetch_broken_pool.assert_not_called()


def test_api_limit_up_ladder(tmp_path: Path) -> None:
    client = _client(_service(tmp_path))
    response = client.get("/api/v1/market/limit-up/ladder", params={"trade_date": "2026-09-30"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "2026-09-30"
    assert payload["summary"]["max_board"] == 7
    assert payload["tiers"][0]["board_days"] == 7
