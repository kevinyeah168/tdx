from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.config import WorkbenchSettings
from workbench.domain import SectorGrayMinute, StockGrayMinute
from workbench.storage.hot_store import HotStore

TRADE_DATE = date(2026, 8, 20)


def _seed_gray_minute(data_dir: Path) -> None:
    settings = WorkbenchSettings(data_dir=data_dir)
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    hot.write_stock_gray(
        [
            StockGrayMinute(
                trade_date=TRADE_DATE,
                minute="09:31",
                symbol="SH600000",
                code="600000",
                open_cum=120_000_000.0,
                dark_cum=350_000_000.0,
                total_cum=470_000_000.0,
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id="test-gray",
                source="eastmoney:graymarket:darktrade",
            )
        ]
    )


def test_stock_gray_flow_contract(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    _seed_gray_minute(tmp_path)
    client = TestClient(create_app(WorkbenchSettings(data_dir=tmp_path)))

    response = client.get("/api/v1/stocks/sh600000/gray-flow?date=2026-08-20")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "SH600000",
        "latest_complete_minute": "09:31",
        "points": [
            {
                "minute": "09:31",
                "dark_cumulative": 350_000_000.0,
                "open_cumulative": 120_000_000.0,
                "total_cumulative": 470_000_000.0,
                "source": "eastmoney:graymarket:darktrade",
            }
        ],
    }


def _seed_sector_gray_minute(data_dir: Path) -> None:
    settings = WorkbenchSettings(data_dir=data_dir)
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    hot.write_sector_gray(
        [
            SectorGrayMinute(
                trade_date=TRADE_DATE,
                minute="09:31",
                sector_id="881001",
                member_count=20,
                gray_covered_count=18,
                open_cum=50_000_000.0,
                dark_cum=120_000_000.0,
                total_cum=170_000_000.0,
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id="test-sector-gray",
            )
        ]
    )


def test_sector_gray_flow_contract(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    _seed_sector_gray_minute(tmp_path)
    client = TestClient(create_app(WorkbenchSettings(data_dir=tmp_path)))

    response = client.get("/api/v1/sectors/881001/gray-flow?date=2026-08-20")

    assert response.status_code == 200
    assert response.json() == {
        "sector_id": "881001",
        "latest_complete_minute": "09:31",
        "member_count": 20,
        "gray_covered_count": 18,
        "coverage_pct": 90.0,
        "source": "constituent_sum:eastmoney:graymarket:darktrade",
        "quality": "aggregated",
        "points": [
            {
                "minute": "09:31",
                "dark_cumulative": 120_000_000.0,
                "open_cumulative": 50_000_000.0,
                "total_cumulative": 170_000_000.0,
                "source": "constituent_sum:eastmoney:graymarket:darktrade",
            }
        ],
    }


def test_sector_gray_flow_batch_contract(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    _seed_sector_gray_minute(tmp_path)
    client = TestClient(create_app(WorkbenchSettings(data_dir=tmp_path)))

    response = client.post(
        "/api/v1/sectors/gray-flow/batch?date=2026-08-20",
        json={"ids": ["881001", "881002"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "2026-08-20"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["sector_id"] == "881001"


def test_stock_gray_flow_not_found(tmp_path: Path) -> None:
    from workbench.api.main import create_app

    settings = WorkbenchSettings(data_dir=tmp_path)
    HotStore(settings.hot_db_for(TRADE_DATE.isoformat())).initialize()
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/stocks/sh600000/gray-flow?date=2026-08-20")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "SH600000",
        "latest_complete_minute": "",
        "points": [],
    }
