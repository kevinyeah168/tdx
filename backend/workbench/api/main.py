from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from workbench.api.routes_hot_list import create_hot_list_router
from workbench.api.routes_limit_up import create_limit_up_router
from workbench.api.routes_market import (
    create_market_router,
    create_sector_router,
    create_settings_router,
)
from workbench.api.tdx_hot import get_hot_enhanced_client
from workbench.providers.tdx.board_sectors import supplement_classic_index_quotes
from workbench.api.routes_replay import create_replay_router
from workbench.api.routes_stocks import create_stock_router
from workbench.collector.heartbeat import seed_demo_history
from workbench.config import WorkbenchSettings, merge_user_config, workbench_settings_from_environment
from workbench.services.custom_sector_sync_runner import custom_sector_sync_loop
from workbench.providers.tdx.runtime import create_real_provider
from workbench.query.custom_sector_flow import CustomSectorFlowService
from workbench.query.custom_sector_ids import is_custom_sector_id
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


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
    amount_delta: float | None = None


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
    pre_close: float | None = None


class GrayCurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    minute: str
    dark_cumulative: float
    open_cumulative: float | None = None
    total_cumulative: float | None = None
    source: str | None = None


class StockGrayFlowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str
    latest_complete_minute: str
    points: list[GrayCurvePoint]


class SectorGrayFlowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str
    latest_complete_minute: str
    member_count: int | None = None
    gray_covered_count: int | None = None
    coverage_pct: float | None = None
    source: str | None = None
    quality: str | None = None
    points: list[GrayCurvePoint]


class IdsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ids: list[str] = Field(default_factory=list, max_length=200)


class SectorFundFlowBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    items: list[SectorFundFlowPayload]


class StockFundFlowBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    items: list[StockFundFlowPayload]


class StockGrayFlowBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    items: list[StockGrayFlowPayload]


class SectorGrayFlowBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    items: list[SectorGrayFlowPayload]


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


def _optional_hot_store(settings: WorkbenchSettings, trade_date: date) -> HotStore | None:
    path = settings.hot_db_for(trade_date.isoformat())
    if not path.is_file():
        return None
    store = HotStore(path)
    store.initialize()
    return store


def _meta_store(settings: WorkbenchSettings) -> MetaStore:
    store = MetaStore(settings.meta_db)
    store.initialize()
    return store


def _sector_fund_curve(
    settings: WorkbenchSettings,
    trade_date: date,
    sector_id: str,
    store: HotStore,
) -> Any:
    if is_custom_sector_id(sector_id):
        return CustomSectorFlowService(_meta_store(settings), store).complete_fund_curve(
            trade_date.isoformat(),
            sector_id,
        )
    return store.complete_sector_fund_curve(trade_date.isoformat(), sector_id)


def _sector_gray_curve(
    settings: WorkbenchSettings,
    trade_date: date,
    sector_id: str,
    store: HotStore,
) -> Any:
    if is_custom_sector_id(sector_id):
        return CustomSectorFlowService(_meta_store(settings), store).sector_gray_curve(
            trade_date.isoformat(),
            sector_id,
        )
    return store.sector_gray_curve(trade_date.isoformat(), sector_id)


def _serialize_gray_curve(*, symbol: str, curve: Any) -> StockGrayFlowPayload:
    if not curve.rows or curve.latest_complete_minute is None:
        return StockGrayFlowPayload.model_validate(
            {
                "symbol": symbol,
                "latest_complete_minute": "",
                "points": [],
            }
        )
    points: list[dict[str, Any]] = []
    for row in curve.rows:
        point: dict[str, Any] = {
            "minute": row["minute"],
            "dark_cumulative": float(row["dark_cum"]),
        }
        if row.get("open_cum") is not None:
            point["open_cumulative"] = float(row["open_cum"])
        if row.get("total_cum") is not None:
            point["total_cumulative"] = float(row["total_cum"])
        if row.get("source") is not None:
            point["source"] = str(row["source"])
        points.append(point)
    return StockGrayFlowPayload.model_validate(
        {
            "symbol": symbol,
            "latest_complete_minute": curve.latest_complete_minute,
            "points": points,
        }
    )


def _serialize_sector_gray_curve(*, sector_id: str, curve: Any) -> SectorGrayFlowPayload:
    if not curve.rows or curve.latest_complete_minute is None:
        return SectorGrayFlowPayload.model_validate(
            {
                "sector_id": sector_id,
                "latest_complete_minute": "",
                "points": [],
            }
        )
    points: list[dict[str, Any]] = []
    latest_row = curve.rows[-1]
    for row in curve.rows:
        point: dict[str, Any] = {
            "minute": row["minute"],
            "dark_cumulative": float(row["dark_cum"]),
        }
        if row.get("open_cum") is not None:
            point["open_cumulative"] = float(row["open_cum"])
        if row.get("total_cum") is not None:
            point["total_cumulative"] = float(row["total_cum"])
        if row.get("source") is not None:
            point["source"] = str(row["source"])
        points.append(point)
    member_count = latest_row.get("member_count")
    gray_covered_count = latest_row.get("gray_covered_count")
    coverage_pct = None
    if member_count and gray_covered_count is not None:
        try:
            coverage_pct = round(float(gray_covered_count) / float(member_count) * 100.0, 2)
        except ZeroDivisionError:
            coverage_pct = None
    return SectorGrayFlowPayload.model_validate(
        {
            "sector_id": sector_id,
            "latest_complete_minute": curve.latest_complete_minute,
            "member_count": int(member_count) if member_count is not None else None,
            "gray_covered_count": int(gray_covered_count) if gray_covered_count is not None else None,
            "coverage_pct": coverage_pct,
            "source": str(latest_row.get("source") or "") or None,
            "quality": str(latest_row.get("quality") or "") or None,
            "points": points,
        }
    )


def _point_extras(row: dict[str, Any]) -> dict[str, float]:
    extras: dict[str, float] = {}
    if row.get("close") is not None:
        extras["close"] = float(row["close"])
    if row.get("change_pct") is not None:
        extras["change_pct"] = float(row["change_pct"])
    if row.get("amount_delta") is not None:
        extras["amount_delta"] = float(row["amount_delta"])
    return extras


def _fetch_sector_pre_close(sector_id: str, enhanced_client: object | None) -> float | None:
    if enhanced_client is None:
        return None
    get_stock_quotes = getattr(enhanced_client, "get_stock_quotes", None)
    quote_map: dict[str, tuple[float, float]] = {}
    if callable(get_stock_quotes):
        try:
            supplement_classic_index_quotes(
                quote_map,
                sector_ids=[sector_id],
                get_stock_quotes=get_stock_quotes,
            )
            response = get_stock_quotes([(1, sector_id)])
            rows = response if isinstance(response, list) else getattr(response, "data", response)
            if rows:
                for row in rows or []:
                    code = str(
                        row.get("code") if isinstance(row, dict) else getattr(row, "code", "")
                    ).strip()
                    if code != sector_id:
                        continue
                    if isinstance(row, dict):
                        pre_close = float(row.get("pre_close") or 0.0)
                    else:
                        pre_close = float(getattr(row, "pre_close", 0.0) or 0.0)
                    if pre_close > 0:
                        quote_map[sector_id] = (pre_close, pre_close)
        except (RuntimeError, OSError, TypeError, ValueError, AttributeError):
            pass
    get_board_list = getattr(enhanced_client, "get_board_list", None)
    if sector_id not in quote_map and callable(get_board_list):
        try:
            from easy_tdx.mac.enums import BoardType

            for board_type in (BoardType.HY, BoardType.GN, BoardType.HY2, BoardType.FG, BoardType.DQ):
                response = get_board_list(board_type=board_type, count=500)
                rows = response if isinstance(response, list) else getattr(response, "data", response)
                for row in rows or []:
                    code = str(
                        row.get("code") if isinstance(row, dict) else getattr(row, "code", "")
                    ).strip()
                    if code != sector_id:
                        continue
                    if isinstance(row, dict):
                        pre_close = float(row.get("pre_close") or 0.0)
                    else:
                        pre_close = float(getattr(row, "pre_close", 0.0) or 0.0)
                    if pre_close > 0:
                        return pre_close
        except (RuntimeError, OSError, TypeError, ValueError, AttributeError, ImportError):
            pass
    hit = quote_map.get(sector_id)
    if hit is None:
        return None
    _price, pre_close = hit
    return pre_close if pre_close > 0 else None


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
                **_point_extras(row),
            }
            for row in rows
        ],
    }
    if payload_model is SectorFundFlowPayload and rows:
        payload["change_pct"] = float(rows[-1].get("change_pct", 0.0))
    return payload_model.model_validate(payload)


def _serialize_series_optional(
    *,
    entity_key: str,
    entity_id: str,
    latest_complete_minute: str | None,
    rows: list[dict[str, Any]],
    tiers: tuple[str, ...],
    payload_model: type[StockFundFlowPayload] | type[SectorFundFlowPayload],
) -> StockFundFlowPayload | SectorFundFlowPayload | None:
    if not rows or latest_complete_minute is None:
        return None
    return _serialize_series(
        entity_key=entity_key,
        entity_id=entity_id,
        latest_complete_minute=latest_complete_minute,
        rows=rows,
        tiers=tiers,
        payload_model=payload_model,
    )


def _normalize_batch_ids(ids: list[str], *, limit: int = 200) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        code = str(raw).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        merged.append(code)
        if len(merged) >= limit:
            break
    return merged


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
        sync_task = asyncio.create_task(custom_sector_sync_loop(active_settings))
        try:
            yield
        finally:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass
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
    application.include_router(create_hot_list_router())
    application.include_router(create_limit_up_router())
    application.include_router(create_settings_router())
    application.include_router(create_sector_router())
    application.include_router(create_stock_router())
    application.include_router(create_replay_router())

    @application.get("/api/v1/health")
    def health() -> dict[str, object]:
        run_dir = active_settings.data_dir / "run"
        collectors: dict[str, object] = {}
        for role in ("hot", "archive", "combined", "gray", "collector"):
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

    @application.get("/api/v1/stocks/{symbol}/gray-flow", response_model=StockGrayFlowPayload)
    def stock_gray_flow(symbol: str, trade_date: date = Query(alias="date")) -> StockGrayFlowPayload:
        normalized_symbol = symbol.upper()
        try:
            store = _hot_store(active_settings, trade_date)
            curve = store.stock_gray_curve(trade_date.isoformat(), normalized_symbol)
            return _serialize_gray_curve(symbol=normalized_symbol, curve=curve)
        except HTTPException:
            raise
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as error:
            raise _unavailable_storage() from error

    @application.get("/api/v1/sectors/{sector_id}/gray-flow", response_model=SectorGrayFlowPayload)
    def sector_gray_flow(sector_id: str, trade_date: date = Query(alias="date")) -> SectorGrayFlowPayload:
        try:
            store = _hot_store(active_settings, trade_date)
            curve = _sector_gray_curve(active_settings, trade_date, sector_id, store)
            return _serialize_sector_gray_curve(sector_id=sector_id, curve=curve)
        except HTTPException:
            raise
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as error:
            raise _unavailable_storage() from error

    @application.get("/api/v1/sectors/{sector_id}/minutes", response_model=SectorFundFlowPayload)
    def sector_minutes(
        sector_id: str,
        request: Request,
        trade_date: date = Query(alias="date"),
        tiers: str | None = None,
    ) -> SectorFundFlowPayload:
        selected_tiers = _parse_tiers(tiers)
        try:
            store = _hot_store(active_settings, trade_date)
            curve = _sector_fund_curve(active_settings, trade_date, sector_id, store)
            payload = _serialize_series(
                entity_key="sector_id",
                entity_id=sector_id,
                latest_complete_minute=curve.latest_complete_minute,
                rows=curve.rows,
                tiers=selected_tiers,
                payload_model=SectorFundFlowPayload,
            )
            if is_custom_sector_id(sector_id):
                return payload
            enhanced_client = None
            try:
                enhanced_client = get_hot_enhanced_client(request)
            except RuntimeError:
                enhanced_client = None
            pre_close = _fetch_sector_pre_close(sector_id, enhanced_client)
            if pre_close is None:
                return payload
            body = payload.model_dump()
            body["pre_close"] = pre_close
            return SectorFundFlowPayload.model_validate(body)
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as error:
            raise _unavailable_storage() from error

    @application.post("/api/v1/sectors/fund-flow/batch", response_model=SectorFundFlowBatchResponse)
    def sector_fund_flow_batch(
        payload: IdsBatchRequest,
        trade_date: date = Query(alias="date"),
        tiers: str | None = None,
    ) -> SectorFundFlowBatchResponse:
        selected_tiers = _parse_tiers(tiers)
        store = _optional_hot_store(active_settings, trade_date)
        if store is None:
            return SectorFundFlowBatchResponse(trade_date=trade_date.isoformat(), items=[])
        trade_date_str = trade_date.isoformat()
        items: list[SectorFundFlowPayload] = []
        normalized_ids = _normalize_batch_ids(payload.ids)
        catalog_ids = [
            sector_id for sector_id in normalized_ids if not is_custom_sector_id(sector_id)
        ]
        custom_ids = [sector_id for sector_id in normalized_ids if is_custom_sector_id(sector_id)]
        try:
            catalog_curves = store.complete_sector_fund_curves_batch(trade_date_str, catalog_ids)
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
            catalog_curves = {}
        for sector_id in catalog_ids:
            curve = catalog_curves.get(sector_id)
            if curve is None:
                continue
            serialized = _serialize_series_optional(
                entity_key="sector_id",
                entity_id=sector_id,
                latest_complete_minute=curve.latest_complete_minute,
                rows=curve.rows,
                tiers=selected_tiers,
                payload_model=SectorFundFlowPayload,
            )
            if serialized is not None:
                items.append(serialized)
        for sector_id in custom_ids:
            try:
                curve = _sector_fund_curve(active_settings, trade_date, sector_id, store)
                serialized = _serialize_series_optional(
                    entity_key="sector_id",
                    entity_id=sector_id,
                    latest_complete_minute=curve.latest_complete_minute,
                    rows=curve.rows,
                    tiers=selected_tiers,
                    payload_model=SectorFundFlowPayload,
                )
            except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
                continue
            if serialized is not None:
                items.append(serialized)
        return SectorFundFlowBatchResponse(trade_date=trade_date_str, items=items)

    @application.post("/api/v1/stocks/fund-flow/batch", response_model=StockFundFlowBatchResponse)
    def stock_fund_flow_batch(
        payload: IdsBatchRequest,
        trade_date: date = Query(alias="date"),
        tiers: str | None = None,
    ) -> StockFundFlowBatchResponse:
        selected_tiers = _parse_tiers(tiers)
        store = _optional_hot_store(active_settings, trade_date)
        if store is None:
            return StockFundFlowBatchResponse(trade_date=trade_date.isoformat(), items=[])
        trade_date_str = trade_date.isoformat()
        items: list[StockFundFlowPayload] = []
        symbols = [raw_symbol.upper() for raw_symbol in _normalize_batch_ids(payload.ids)]
        try:
            curves = store.live_stock_fund_curves_batch(trade_date_str, symbols)
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
            curves = {}
        for symbol in symbols:
            curve = curves.get(symbol)
            if curve is None:
                continue
            serialized = _serialize_series_optional(
                entity_key="symbol",
                entity_id=symbol,
                latest_complete_minute=curve.latest_complete_minute,
                rows=curve.rows,
                tiers=selected_tiers,
                payload_model=StockFundFlowPayload,
            )
            if serialized is not None:
                items.append(serialized)
        return StockFundFlowBatchResponse(trade_date=trade_date_str, items=items)

    @application.post("/api/v1/stocks/gray-flow/batch", response_model=StockGrayFlowBatchResponse)
    def stock_gray_flow_batch(
        payload: IdsBatchRequest,
        trade_date: date = Query(alias="date"),
    ) -> StockGrayFlowBatchResponse:
        store = _optional_hot_store(active_settings, trade_date)
        if store is None:
            return StockGrayFlowBatchResponse(trade_date=trade_date.isoformat(), items=[])
        trade_date_str = trade_date.isoformat()
        items: list[StockGrayFlowPayload] = []
        symbols = [raw_symbol.upper() for raw_symbol in _normalize_batch_ids(payload.ids)]
        try:
            curves = store.stock_gray_curves_batch(trade_date_str, symbols)
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
            curves = {}
        for symbol in symbols:
            curve = curves.get(symbol)
            if curve is None:
                continue
            try:
                items.append(_serialize_gray_curve(symbol=symbol, curve=curve))
            except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
                continue
        return StockGrayFlowBatchResponse(trade_date=trade_date_str, items=items)

    @application.post("/api/v1/sectors/gray-flow/batch", response_model=SectorGrayFlowBatchResponse)
    def sector_gray_flow_batch(
        payload: IdsBatchRequest,
        trade_date: date = Query(alias="date"),
    ) -> SectorGrayFlowBatchResponse:
        store = _optional_hot_store(active_settings, trade_date)
        if store is None:
            return SectorGrayFlowBatchResponse(trade_date=trade_date.isoformat(), items=[])
        trade_date_str = trade_date.isoformat()
        items: list[SectorGrayFlowPayload] = []
        normalized_ids = _normalize_batch_ids(payload.ids)
        catalog_ids = [
            sector_id for sector_id in normalized_ids if not is_custom_sector_id(sector_id)
        ]
        custom_ids = [sector_id for sector_id in normalized_ids if is_custom_sector_id(sector_id)]
        try:
            catalog_curves = store.sector_gray_curves_batch(trade_date_str, catalog_ids)
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
            catalog_curves = {}
        for sector_id in catalog_ids:
            curve = catalog_curves.get(sector_id)
            if curve is None:
                continue
            try:
                serialized = _serialize_sector_gray_curve(sector_id=sector_id, curve=curve)
            except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
                continue
            if serialized.points:
                items.append(serialized)
        for sector_id in custom_ids:
            try:
                curve = _sector_gray_curve(active_settings, trade_date, sector_id, store)
                serialized = _serialize_sector_gray_curve(sector_id=sector_id, curve=curve)
            except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
                continue
            if serialized.points:
                items.append(serialized)
        return SectorGrayFlowBatchResponse(trade_date=trade_date_str, items=items)

    return application


app = create_app()
