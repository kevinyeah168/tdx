from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api.main import create_app
from workbench.config import WorkbenchSettings
from workbench.domain import Membership, Sector, Security
from workbench.storage.meta_store import MetaStore


def test_stock_bars_returns_fixture_rows_for_demo_data_dir(tmp_path: Path) -> None:
    demo_dir = tmp_path / "workbench-demo"
    demo_dir.mkdir()
    settings = WorkbenchSettings(data_dir=demo_dir)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    meta.replace_catalog(
        securities=[Security(symbol="SH600000", code="600000", name="浦发银行", market="SH")],
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=[Membership(sector_id="881001", symbol="SH600000")],
        version="catalog-test",
        source="test",
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/stocks/SH600000/bars", params={"period": "day", "count": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "SH600000"
    assert len(payload["bars"]) == 2
