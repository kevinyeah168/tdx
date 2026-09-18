from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api.main import create_app
from workbench.config import WorkbenchSettings
from workbench.domain import Membership, Sector, Security
from workbench.storage.history_store import HistoryStore
from workbench.storage.meta_store import MetaStore
from workbench.providers.tdx.bars import normalize_bar_row
import json


def seed(tmp_path: Path) -> WorkbenchSettings:
    settings = WorkbenchSettings(data_dir=tmp_path / "workbench-demo")
    settings.ensure_directories()
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    meta.replace_catalog(
        securities=[Security(symbol="SH600000", code="600000", name="浦发银行", market="SH")],
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=[Membership(sector_id="881001", symbol="SH600000")],
        version="catalog-test",
        source="test",
    )
    history = HistoryStore(settings.data_dir / "history" / "bars.sqlite")
    history.initialize()
    rows = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "tdx" / "bars.json").read_text(encoding="utf-8")
    )
    bars = [normalize_bar_row(row, symbol="SH600000", period="day") for row in rows]
    history.replace_bars(symbol="SH600000", period="day", bars=bars, source="test")
    return settings


def test_stock_detail_api(tmp_path: Path) -> None:
    client = TestClient(create_app(seed(tmp_path)))
    response = client.get("/api/v1/stocks/SH600000")
    assert response.status_code == 200
    assert response.json()["name"] == "浦发银行"


def test_stock_bars_api(tmp_path: Path) -> None:
    client = TestClient(create_app(seed(tmp_path)))
    response = client.get("/api/v1/stocks/SH600000/bars", params={"period": "day", "count": 2})
    assert response.status_code == 200
    assert len(response.json()["bars"]) == 2


def test_settings_api(tmp_path: Path) -> None:
    client = TestClient(create_app(seed(tmp_path)))
    payload = client.get("/api/v1/settings").json()
    assert payload["retention_days"] == 365
    assert payload["collect_mode"] == "selective"
    response = client.put("/api/v1/settings", json={"retention_days": 45})
    assert response.status_code == 200
    assert response.json()["retention_days"] == 45


def test_health_detail_api(tmp_path: Path) -> None:
    client = TestClient(create_app(seed(tmp_path)))
    response = client.get("/api/v1/health/detail")
    assert response.status_code == 200
    payload = response.json()
    assert "catalog_stale" in payload
    assert "collector_roles" in payload


def test_health_detail_reports_hot_collector(tmp_path: Path) -> None:
    from workbench.collector.heartbeat import write_collector_heartbeat

    settings = seed(tmp_path)
    write_collector_heartbeat(settings.data_dir, role="hot")
    client = TestClient(create_app(settings))
    response = client.get("/api/v1/health/detail")
    assert response.status_code == 200
    payload = response.json()
    assert payload["collector_online"] is True
    assert payload["collector_roles"]["hot"]["online"] is True
