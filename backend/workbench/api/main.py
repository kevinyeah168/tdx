from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, ValidationError

from workbench.config import WorkbenchSettings
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


class CurvePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    latest_complete_minute: str
    fund_tiers: list[str]
    points: list[CurvePoint]


class StockFundFlowPayload(CurvePayload):
    symbol: str


class SectorFundFlowPayload(CurvePayload):
    sector_id: str


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
    return payload_model.model_validate({
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
            }
            for row in rows
        ],
    })


def _unavailable_storage() -> HTTPException:
    return HTTPException(status_code=503, detail="fund-flow storage is unavailable")


def create_app(settings: WorkbenchSettings | None = None) -> FastAPI:
    active_settings = settings or WorkbenchSettings()
    application = FastAPI(title="TDX Market Workbench", version="0.1.0")

    @application.get("/api/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/api/v1/stocks/{symbol}/fund-flow", response_model=StockFundFlowPayload)
    def stock_fund_flow(
        symbol: str, trade_date: date = Query(alias="date"), tiers: str | None = None
    ) -> StockFundFlowPayload:
        selected_tiers = _parse_tiers(tiers)
        normalized_symbol = symbol.upper()
        try:
            store = _hot_store(active_settings, trade_date)
            curve = store.complete_stock_fund_curve(trade_date.isoformat(), normalized_symbol)
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
