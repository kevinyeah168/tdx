from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from workbench.api.routes_market import get_settings
from workbench.collector.trading_clock import AUCTION_BOARD_DEFAULT_SORT, AUCTION_BOARD_SORT_KEYS
from workbench.config import WorkbenchSettings
from workbench.providers.eastmoney.auction_board import AUCTION_BOARD_RANK_LIMIT
from workbench.services.auction_board import AuctionBoardResponse, AuctionBoardService, get_auction_board_service


def create_auction_board_router(
    service: AuctionBoardService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/market/auction-board", tags=["market-auction-board"])
    board_service = service or get_auction_board_service()

    @router.get("", response_model=AuctionBoardResponse)
    def auction_board(
        settings: WorkbenchSettings = Depends(get_settings),
        trade_date: str | None = Query(default=None, description="交易日 YYYY-MM-DD，默认当天"),
        sort: str = Query(default=AUCTION_BOARD_DEFAULT_SORT, description="排序：ratio/amount/change/volume/price"),
        limit: int = Query(default=AUCTION_BOARD_RANK_LIMIT, ge=1, le=AUCTION_BOARD_RANK_LIMIT),
        force: bool = Query(default=False, description="强制刷新上游并覆盖当日快照"),
    ) -> AuctionBoardResponse:
        board_service.bind_settings(settings)
        resolved_date = trade_date or date.today().isoformat()
        if sort not in AUCTION_BOARD_SORT_KEYS:
            raise HTTPException(status_code=400, detail=f"invalid sort: {sort}")
        try:
            return board_service.board(resolved_date, sort=sort, limit=limit, force=force)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router
