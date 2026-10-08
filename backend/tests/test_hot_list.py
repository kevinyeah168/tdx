from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api.routes_hot_list import create_hot_list_router
from workbench.providers.eastmoney.hot_rank import EastMoneyHotStockRow
from workbench.providers.tonghuashun.hot_rank import TonghuashunHotBoardRow, TonghuashunHotStockRow
from workbench.services.hot_list import HotListService, HotStockItem


def _service() -> HotListService:
    eastmoney = MagicMock()
    tonghuashun = MagicMock()
    eastmoney.fetch_stock_rank.return_value = [
        EastMoneyHotStockRow(
            rank=1,
            symbol="SH600519",
            code="600519",
            name="贵州茅台",
            price=1700.0,
            change_pct=1.2,
            rank_change=3,
        )
    ]
    tonghuashun.fetch_stock_rank.return_value = [
        TonghuashunHotStockRow(
            rank=1,
            symbol="SZ300308",
            code="300308",
            name="中际旭创",
            change_pct=-0.56,
            hot_value=134528.0,
            rank_change=0,
        )
    ]
    tonghuashun.fetch_board_rank.return_value = [
        TonghuashunHotBoardRow(
            rank=1,
            board_code="886015",
            name="创新药",
            change_pct=2.46,
            hot_value=10890.5,
            rank_change=0,
        )
    ]
    return HotListService(eastmoney=eastmoney, tonghuashun=tonghuashun, cache_ttl=60)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_hot_list_router(service=_service()))
    return TestClient(app)


def test_hot_stocks_single_source() -> None:
    client = _client()
    response = client.get(
        "/api/v1/market/hot/stocks",
        params={"board": "popularity", "source": "eastmoney"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["board"] == "popularity"
    assert payload["source"] == "eastmoney"
    assert payload["items"][0]["symbol"] == "SH600519"
    assert payload["items"][0]["name"] == "贵州茅台"


def test_hot_stocks_both_sources() -> None:
    client = _client()
    response = client.get(
        "/api/v1/market/hot/stocks",
        params={"board": "surge", "source": "both"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "both"
    assert payload["items"] == []
    assert payload["eastmoney"][0]["source"] == "eastmoney"
    assert payload["ths"][0]["source"] == "ths"


def test_hot_boards_concept() -> None:
    client = _client()
    response = client.get("/api/v1/market/hot/boards", params={"type": "concept"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["board_type"] == "concept"
    assert payload["source"] == "ths"
    assert payload["items"][0]["board_code"] == "886015"


def test_enrich_stock_items_uses_catalog_names() -> None:
    meta = MagicMock()
    meta.security_names.return_value = {"SH600519": "贵州茅台"}
    meta.security_names_by_codes.return_value = {}
    service = HotListService(
        eastmoney=MagicMock(),
        tonghuashun=MagicMock(),
        cache_ttl=60,
    )
    items = [
        HotStockItem(
            rank=1,
            symbol="SH600519",
            code="600519",
            name="600519",
            source="eastmoney",
        )
    ]
    enriched = service._enrich_stock_items(items, meta=meta, settings=None, quote_client=None)
    assert enriched[0].name == "贵州茅台"


def test_enrich_stock_items_uses_eastmoney_name_fallback() -> None:
    meta = MagicMock()
    meta.security_names.return_value = {}
    meta.security_names_by_codes.return_value = {}
    service = HotListService(
        eastmoney=MagicMock(),
        tonghuashun=MagicMock(),
        cache_ttl=60,
    )
    items = [
        HotStockItem(
            rank=433,
            symbol="BJ920252",
            code="920252",
            name="920252",
            source="eastmoney",
        )
    ]
    with patch(
        "workbench.services.hot_list.fetch_security_names_by_codes",
        return_value={"920252": "天宏锂电"},
    ):
        enriched = service._enrich_stock_items(items, meta=meta, settings=None, quote_client=None)
    assert enriched[0].name == "天宏锂电"


def test_enrich_stock_items_uses_ths_name_fallback() -> None:
    meta = MagicMock()
    meta.security_names.return_value = {}
    meta.security_names_by_codes.return_value = {}
    service = HotListService(
        eastmoney=MagicMock(),
        tonghuashun=MagicMock(),
        cache_ttl=60,
    )
    items = [
        HotStockItem(
            rank=2,
            symbol="SZ001246",
            code="001246",
            name="001246",
            source="eastmoney",
        )
    ]
    enriched = service._enrich_stock_items(
        items,
        meta=meta,
        settings=None,
        quote_client=None,
        name_fallback={"SZ001246": "远源信息", "001246": "远源信息"},
    )
    assert enriched[0].name == "远源信息"
