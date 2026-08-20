from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.config import WorkbenchSettings
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


TRADE_DATE = date(2026, 8, 20)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = FakeMarketProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    MinuteCollector(provider, meta, hot).collect(TRADE_DATE, "09:31")
    return TestClient(create_app(settings))


def test_health_and_default_stock_fund_flow_contract(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"ok": True}

    response = client.get("/api/v1/stocks/sh600000/fund-flow?date=2026-08-20")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "SH600000",
        "latest_complete_minute": "09:31",
        "fund_tiers": ["main", "super", "large"],
        "points": [
            {
                "minute": "09:31",
                "values": {
                    "main": {
                        "delta": -1142.0,
                        "cumulative": -2284.0,
                        "source": "fake_provider",
                        "quality": "estimated",
                    },
                    "super": {
                        "delta": -571.0,
                        "cumulative": -1142.0,
                        "source": "fake_provider",
                        "quality": "estimated",
                    },
                    "large": {
                        "delta": -571.0,
                        "cumulative": -1142.0,
                        "source": "fake_provider",
                        "quality": "estimated",
                    },
                },
            }
        ],
    }


def test_sector_uses_the_shared_payload_shape_and_preserves_provenance(client: TestClient) -> None:
    response = client.get(
        "/api/v1/sectors/880000/minutes?date=2026-08-20&tiers=small,medium"
    )

    assert response.status_code == 200
    assert response.json()["sector_id"] == "880000"
    assert response.json()["latest_complete_minute"] == "09:31"
    assert response.json()["fund_tiers"] == ["small", "medium"]
    assert response.json()["points"] == [
        {
            "minute": "09:31",
            "values": {
                "small": {
                    "delta": 4000.0,
                    "cumulative": 8000.0,
                    "source": "constituent_sum",
                    "quality": "aggregated",
                },
                "medium": {
                    "delta": 4000.0,
                    "cumulative": 8000.0,
                    "source": "constituent_sum",
                    "quality": "aggregated",
                },
            },
        }
    ]


def test_stock_all_five_requested_tiers_preserve_order(client: TestClient) -> None:
    response = client.get(
        "/api/v1/stocks/SH600000/fund-flow?date=2026-08-20&tiers=small,main,medium,large,super"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["fund_tiers"] == ["small", "main", "medium", "large", "super"]
    assert list(payload["points"][0]["values"]) == payload["fund_tiers"]


@pytest.mark.parametrize(
    "query, message",
    [
        ("tiers=main,unknown", "unknown"),
        ("tiers=main,main", "duplicate"),
        ("tiers=", "blank"),
    ],
)
def test_invalid_tiers_return_clear_bad_request(client: TestClient, query: str, message: str) -> None:
    response = client.get(f"/api/v1/stocks/SH600000/fund-flow?date=2026-08-20&{query}")

    assert response.status_code == 400
    assert message in response.json()["detail"].lower()


def test_missing_date_or_data_and_invalid_date_are_controlled_and_read_only(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path / "empty")
    client = TestClient(create_app(settings))

    missing_date = client.get("/api/v1/stocks/SH600000/fund-flow?date=2026-08-20")
    invalid_date = client.get("/api/v1/stocks/SH600000/fund-flow?date=../../secrets")

    assert missing_date.status_code == 404
    assert invalid_date.status_code in {400, 422}
    assert not settings.data_dir.exists()


def test_missing_entity_data_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/stocks/SH999999/fund-flow?date=2026-08-20")

    assert response.status_code == 404


def test_partial_and_uncommitted_rows_are_never_visible_after_later_complete_minute(
    tmp_path: Path,
) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = FakeMarketProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    hot.write_stocks(provider.minute_batch(TRADE_DATE, "09:31").stocks)
    MinuteCollector(provider, meta, hot).collect(TRADE_DATE, "09:32")
    client = TestClient(create_app(settings))

    stock = client.get("/api/v1/stocks/SH600000/fund-flow?date=2026-08-20")
    sector = client.get("/api/v1/sectors/880000/minutes?date=2026-08-20")

    assert stock.status_code == sector.status_code == 200
    assert stock.json()["latest_complete_minute"] == sector.json()["latest_complete_minute"] == "09:32"
    assert [point["minute"] for point in stock.json()["points"]] == ["09:32"]
    assert [point["minute"] for point in sector.json()["points"]] == ["09:32"]


def test_persisted_partial_batch_is_hidden_after_a_later_complete_minute(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    class PartialFirstMinuteProvider(FakeMarketProvider):
        def minute_batch(self, trade_date: date, minute: str):  # type: ignore[no-untyped-def]
            batch = super().minute_batch(trade_date, minute)
            if minute == "09:31":
                return batch.model_copy(update={"stocks": batch.stocks[:-1]})
            return batch

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = PartialFirstMinuteProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    collector = MinuteCollector(provider, meta, hot)
    partial_result = collector.collect(TRADE_DATE, "09:31")
    collector.collect(TRADE_DATE, "09:32")
    client = TestClient(create_app(settings))

    stock = client.get("/api/v1/stocks/SH600000/fund-flow?date=2026-08-20")
    sector = client.get("/api/v1/sectors/880000/minutes?date=2026-08-20")
    with hot._session(readonly=True) as connection:
        persisted_status = connection.execute(
            "SELECT status FROM collection_status WHERE trade_date=? AND minute=?",
            ("2026-08-20", "09:31"),
        ).fetchone()[0]

    assert partial_result["status"] == persisted_status == "partial"
    assert stock.status_code == sector.status_code == 200
    assert stock.json()["latest_complete_minute"] == sector.json()["latest_complete_minute"] == "09:32"
    assert [point["minute"] for point in stock.json()["points"]] == ["09:32"]
    assert [point["minute"] for point in sector.json()["points"]] == ["09:32"]


def test_market_cursor_can_advance_past_an_entitys_last_visible_point(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    class OperationallyCompleteProvider(FakeMarketProvider):
        def minute_batch(self, trade_date: date, minute: str):  # type: ignore[no-untyped-def]
            batch = super().minute_batch(trade_date, minute)
            if minute == "09:32":
                return batch.model_copy(
                    update={"stocks": [stock for stock in batch.stocks if stock.symbol != "SH600000"]}
                )
            return batch

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = OperationallyCompleteProvider(200, 2, 100)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    collector = MinuteCollector(provider, meta, hot)
    collector.collect(TRADE_DATE, "09:31")
    completed = collector.collect(TRADE_DATE, "09:32")
    response = TestClient(create_app(settings)).get(
        "/api/v1/stocks/SH600000/fund-flow?date=2026-08-20"
    )

    assert completed["status"] == "complete"
    assert response.status_code == 200
    assert response.json()["latest_complete_minute"] == "09:32"
    assert [point["minute"] for point in response.json()["points"]] == ["09:31"]


def test_mismatched_batch_rows_are_not_exposed_by_complete_status(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = FakeMarketProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    MinuteCollector(provider, meta, hot).collect(TRADE_DATE, "09:31")
    raw_stock = provider.minute_batch(TRADE_DATE, "09:31").stocks[0].model_copy(
        update={"batch_id": "out-of-band"}
    )
    hot.write_stocks([raw_stock])
    with hot._session() as connection:
        connection.execute(
            "UPDATE sector_minute SET batch_id='out-of-band' "
            "WHERE trade_date=? AND minute=? AND sector_id=?",
            ("2026-08-20", "09:31", "880000"),
        )
    client = TestClient(create_app(settings))

    stock = client.get("/api/v1/stocks/SH600000/fund-flow?date=2026-08-20")
    sector = client.get("/api/v1/sectors/880000/minutes?date=2026-08-20")

    assert stock.status_code == sector.status_code == 404


def test_closed_database_read_creates_no_wal_or_shm_artifacts(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = FakeMarketProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    MinuteCollector(provider, meta, hot).collect(TRADE_DATE, "09:31")
    with hot._session() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    wal_path = Path(f"{hot.path}-wal")
    shm_path = Path(f"{hot.path}-shm")
    assert not wal_path.exists()
    assert not shm_path.exists()

    response = TestClient(create_app(settings)).get(
        "/api/v1/stocks/SH600000/fund-flow?date=2026-08-20"
    )

    assert response.status_code == 200
    assert not wal_path.exists()
    assert not shm_path.exists()


def test_live_wal_data_remains_visible_to_api_reads(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = FakeMarketProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    writer = hot.connect()
    try:
        MinuteCollector(provider, meta, hot).collect(TRADE_DATE, "09:31")
        assert Path(f"{hot.path}-wal").exists()

        response = TestClient(create_app(settings)).get(
            "/api/v1/stocks/SH600000/fund-flow?date=2026-08-20"
        )
    finally:
        writer.close()

    assert response.status_code == 200
    assert response.json()["points"][0]["minute"] == "09:31"


@pytest.mark.parametrize("contents", [b"not a sqlite database", None])
def test_storage_failures_return_generic_service_unavailable(
    tmp_path: Path, contents: bytes | None
) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    path = settings.hot_db_for("2026-08-20")
    path.parent.mkdir()
    if contents is None:
        sqlite3.connect(path).close()
    else:
        path.write_bytes(contents)

    response = TestClient(create_app(settings)).get(
        "/api/v1/stocks/SH600000/fund-flow?date=2026-08-20"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "fund-flow storage is unavailable"}


def test_invalid_stored_value_returns_generic_service_unavailable(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    provider = FakeMarketProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    MinuteCollector(provider, meta, hot).collect(TRADE_DATE, "09:31")
    with hot._session() as connection:
        connection.execute(
            "UPDATE stock_minute SET main_delta='invalid' WHERE trade_date=? AND symbol=?",
            ("2026-08-20", "SH600000"),
        )

    response = TestClient(create_app(settings)).get(
        "/api/v1/stocks/SH600000/fund-flow?date=2026-08-20"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "fund-flow storage is unavailable"}


def test_curve_endpoints_publish_strict_response_models(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    stock_schema = document["paths"]["/api/v1/stocks/{symbol}/fund-flow"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    sector_schema = document["paths"]["/api/v1/sectors/{sector_id}/minutes"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]

    assert stock_schema == {"$ref": "#/components/schemas/StockFundFlowPayload"}
    assert sector_schema == {"$ref": "#/components/schemas/SectorFundFlowPayload"}
    assert document["components"]["schemas"]["CurveValue"]["additionalProperties"] is False
