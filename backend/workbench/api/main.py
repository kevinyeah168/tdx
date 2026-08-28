from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, ValidationError

from workbench.api.routes_market import (
    create_market_router,
    create_sector_router,
    create_settings_router,
)
from workbench.api.routes_replay import create_replay_router
from workbench.api.routes_stocks import create_stock_router
from workbench.collector.heartbeat import seed_demo_history
from workbench.config import WorkbenchSettings, merge_user_config, workbench_settings_from_environment
from workbench.providers.tdx.runtime import create_real_provider
from workbench.storage.hot_store import HotStore


DEFAULT_TIERS = ("main", "super", "large")
ALLOWED_TIERS = frozenset((*DEFAULT_TIERS, "medium", "small"))


class CurveValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    delta: float
    cumulative: float
    source: str
    quality: str


class CurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    minute: str
    values: dict[str, CurveValue]
    close: float | None = None
    change_pct: float | None = None


class CurvePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    latest_complete_minute: str
    fund_tiers: list[str]
    points: list[CurvePoint]


class StockFundFlowPayload(CurvePayload):
    symbol: str


class SectorFundFlowPayload(CurvePayload):
    sector_id: str
    change_pct: float | None = None


def _parse_tiers(tiers: str | None) -> tuple[str, ...]:
    if tiers is None:
        return DEFAULT_TIERS
    requested = tuple(part.strip() for part in tiers.split(","))
    if not all(requested):
        raise HTTPException(status_code=400, detail="tiers must not contain blank values")
    duplicate = next((tier for tier in requested if requested.count(tier) > 1), None)
    if duplicate:
        raise HTTPException(status_code=400, detail=f"duplicate tier: {duplicate}")
    unknown = next((tier for tier in requested if tier not in ALLOWED_TIERS), None)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown tier: {unknown}")
    return requested


def _hot_store(settings: WorkbenchSettings, trade_date: date) -> HotStore:
    path = settings.hot_db_for(trade_date.isoformat())
    if not path.is_file():
        raise HTTPException(status_code=404, detail="fund-flow data not found")
    return HotStore(path)


def _serialize_series(
    *,
    entity_key: str,
    entity_id: str,
    latest_complete_minute: str | None,
    rows: list[dict[str, Any]],
    tiers: tuple[str, ...],
    payload_model: type[StockFundFlowPayload] | type[SectorFundFlowPayload],
) -> StockFundFlowPayload | SectorFundFlowPayload:
    if not rows:
        raise HTTPException(status_code=404, detail="fund-flow data not found")
    if latest_complete_minute is None:
        raise HTTPException(status_code=404, detail="fund-flow data not found")
    payload: dict[str, Any] = {
        entity_key: entity_id,
        "latest_complete_minute": latest_complete_minute,
        "fund_tiers": list(tiers),
        "points": [
            {
                "minute": row["minute"],
                "values": {
                    tier: {
                        "delta": row[f"{tier}_delta"],
                        "cumulative": row[f"{tier}_cum"],
                        "source": row["tier_meta"][tier]["source"],
                        "quality": row["tier_meta"][tier]["quality"],
                    }
                    for tier in tiers
                },
                **(
                    {
                        "close": float(row["close"]),
                        "change_pct": float(row["change_pct"]),
                    }
                    if row.get("close") is not None
                    else {}
                ),
            }
            for row in rows
        ],
    }
    if payload_model is SectorFundFlowPayload and rows:
        payload["change_pct"] = float(rows[-1].get("change_pct", 0.0))
    return payload_model.model_validate(payload)


def _unavailable_storage() -> HTTPException:
    return HTTPException(status_code=503, detail="fund-flow storage is unavailable")


def create_app(settings: WorkbenchSettings | None = None) -> FastAPI:
    base_settings = settings if settings is not None else workbench_settings_from_environment()
    active_settings = merge_user_config(base_settings)
    seed_demo_history(active_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        provider = create_real_provider(active_settings)
        application.state.hot_provider = provider
        try:
            yield
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
            application.state.hot_provider = None

    application = FastAPI(title="TDX Market Workbench", version="0.3.0", lifespan=lifespan)
    application.state.workbench_settings = active_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5180",
            "http://localhost:5180",
            "http://127.0.0.1:5181",
            "http://localhost:5181",
        ],
        allow_methods=["GET", "PUT", "POST"],
        allow_headers=["*"],
    )
    application.include_router(create_market_router())
    application.include_router(create_settings_router())
    application.include_router(create_sector_router())
    application.include_router(create_stock_router())
    application.include_router(create_replay_router())

    @application.get("/api/v1/health")
    def health() -> dict[str, object]:
        run_dir = active_settings.data_dir / "run"
        collectors: dict[str, object] = {}
        for role in ("hot", "archive", "collector"):
            path = run_dir / (f"collector-{role}.json" if role != "collector" else "collector.json")
            if path.is_file():
                try:
                    collectors[role] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    collectors[role] = {"stale": True}
        return {"ok": True, "collectors": collectors}

    @application.get("/api/v1/stocks/{symbol}/fund-flow", response_model=StockFundFlowPayload)
    def stock_fund_flow(
        symbol: str, trade_date: date = Query(alias="date"), tiers: str | None = None
    ) -> StockFundFlowPayload:
        selected_tiers = _parse_tiers(tiers)
        normalized_symbol = symbol.upper()
        try:
            store = _hot_store(active_settings, trade_date)
            curve = store.live_stock_fund_curve(trade_date.isoformat(), normalized_symbol)
            return _serialize_series(
                entity_key="symbol",
                entity_id=normalized_symbol,
                latest_complete_minute=curve.latest_complete_minute,
                rows=curve.rows,
                tiers=selected_tiers,
                payload_model=StockFundFlowPayload,
            )
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as error:
            raise _unavailable_storage() from error

    @application.get("/api/v1/sectors/{sector_id}/minutes", response_model=SectorFundFlowPayload)
    def sector_minutes(
        sector_id: str, trade_date: date = Query(alias="date"), tiers: str | None = None
    ) -> SectorFundFlowPayload:
        selected_tiers = _parse_tiers(tiers)
        try:
            store = _hot_store(active_settings, trade_date)
            curve = store.complete_sector_fund_curve(trade_date.isoformat(), sector_id)
            return _serialize_series(
                entity_key="sector_id",
                entity_id=sector_id,
                latest_complete_minute=curve.latest_complete_minute,
                rows=curve.rows,
                tiers=selected_tiers,
                payload_model=SectorFundFlowPayload,
            )
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as error:
            raise _unavailable_storage() from error

    return application


app = create_app()
