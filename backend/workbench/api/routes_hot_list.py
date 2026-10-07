from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from workbench.api.routes_market import get_meta_store, get_settings
from workbench.api.tdx_hot import get_hot_enhanced_client
from workbench.config import WorkbenchSettings
from workbench.services.hot_list import (
    HotBoardListResponse,
    HotListService,
    HotStockListResponse,
    get_hot_list_service,
)
from workbench.storage.meta_store import MetaStore

StockBoard = Literal["popularity", "surge"]
StockSource = Literal["eastmoney", "ths", "both"]
BoardType = Literal["concept", "industry"]


def create_hot_list_router(
    service: HotListService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/market/hot", tags=["market-hot"])
    hot_list_service = service or get_hot_list_service()

    @router.get("/stocks", response_model=HotStockListResponse)
    def hot_stocks(
        request: Request,
        board: StockBoard = Query(description="popularity=人气榜, surge=飙升榜"),
        source: StockSource = Query(default="eastmoney"),
        meta: MetaStore = Depends(get_meta_store),
        settings: WorkbenchSettings = Depends(get_settings),
    ) -> HotStockListResponse:
        quote_client = None
        try:
            quote_client = get_hot_enhanced_client(request)
        except RuntimeError:
            quote_client = None
        try:
            return hot_list_service.stock_list(
                board,
                source,
                meta=meta,
                settings=settings,
                quote_client=quote_client,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/boards", response_model=HotBoardListResponse)
    def hot_boards(
        board_type: BoardType = Query(alias="type", description="concept=概念, industry=行业"),
    ) -> HotBoardListResponse:
        try:
            return hot_list_service.board_list(board_type)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router
