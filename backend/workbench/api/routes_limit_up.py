from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from workbench.api.routes_market import get_settings
from workbench.config import WorkbenchSettings
from workbench.services.limit_up_ladder import LimitUpLadderResponse, LimitUpLadderService, get_limit_up_ladder_service


def create_limit_up_router(
    service: LimitUpLadderService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/market/limit-up", tags=["market-limit-up"])
    ladder_service = service or get_limit_up_ladder_service()

    @router.get("/ladder", response_model=LimitUpLadderResponse)
    def limit_up_ladder(
        settings: WorkbenchSettings = Depends(get_settings),
        trade_date: str | None = Query(default=None, description="交易日 YYYY-MM-DD，默认当天"),
        force: bool = Query(default=False, description="强制刷新上游并覆盖当日快照"),
    ) -> LimitUpLadderResponse:
        ladder_service.bind_settings(settings)
        resolved_date = trade_date or date.today().isoformat()
        try:
            return ladder_service.ladder(resolved_date, force=force)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router
