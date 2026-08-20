from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from workbench.config import WorkbenchSettings
from workbench.storage.hot_store import HotStore


DEFAULT_TIERS = ("main", "super", "large")
ALLOWED_TIERS = frozenset((*DEFAULT_TIERS, "medium", "small"))


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
    *, entity_key: str, entity_id: str, rows: list[dict[str, Any]], tiers: tuple[str, ...]
) -> dict[str, Any]:
    if not rows:
        raise HTTPException(status_code=404, detail="fund-flow data not found")
    return {
        entity_key: entity_id,
        "latest_complete_minute": rows[-1]["minute"],
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
    }


def create_app(settings: WorkbenchSettings | None = None) -> FastAPI:
    active_settings = settings or WorkbenchSettings()
    application = FastAPI(title="TDX Market Workbench", version="0.1.0")

    @application.get("/api/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/api/v1/stocks/{symbol}/fund-flow")
    def stock_fund_flow(
        symbol: str, trade_date: date = Query(alias="date"), tiers: str | None = None
    ) -> dict[str, Any]:
        selected_tiers = _parse_tiers(tiers)
        normalized_symbol = symbol.upper()
        rows = _hot_store(active_settings, trade_date).complete_stock_fund_series(
            trade_date.isoformat(), normalized_symbol
        )
        return _serialize_series(
            entity_key="symbol", entity_id=normalized_symbol, rows=rows, tiers=selected_tiers
        )

    @application.get("/api/v1/sectors/{sector_id}/minutes")
    def sector_minutes(
        sector_id: str, trade_date: date = Query(alias="date"), tiers: str | None = None
    ) -> dict[str, Any]:
        selected_tiers = _parse_tiers(tiers)
        rows = _hot_store(active_settings, trade_date).complete_sector_fund_series(
            trade_date.isoformat(), sector_id
        )
        return _serialize_series(
            entity_key="sector_id", entity_id=sector_id, rows=rows, tiers=selected_tiers
        )

    return application


app = create_app()
