from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api.main import create_app
from workbench.config import WorkbenchSettings
from workbench.domain import Membership, Sector, Security
from workbench.storage.meta_store import MetaStore


def seed_meta(path: Path) -> None:
    store = MetaStore(path)
    store.initialize()
    store.replace_catalog(
        securities=[Security(symbol="SH600000", code="600000", name="浦发银行", market="SH")],
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=[Membership(sector_id="881001", symbol="SH600000")],
        version="catalog-test",
        source="test",
    )


def test_market_overview_api(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    seed_meta(settings.meta_db)
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/market/overview", params={"date": "2026-08-20"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["security_count"] == 1
    assert payload["metadata"]["catalog_version"] == "catalog-test"


def test_sector_list_api(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    seed_meta(settings.meta_db)
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/sectors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["sector_id"] == "881001"
