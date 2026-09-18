from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workbench.api.tdx_hot import get_hot_enhanced_client
from workbench.collector.priority_linkage import (
    read_linkage_sector_id,
    read_linkage_sector_name,
    write_linkage_sector_id,
)
from workbench.collector.priority_sectors import read_priority_sector_ids, write_priority_sector_ids
from workbench.collector.priority_stocks import (
    read_priority_manual_symbols,
    read_priority_stock_symbols,
    write_priority_stock_targets,
)
from workbench.collector.priority_targets import apply_hot_target_sync, resolve_priority_stock_symbols
from workbench.config import WorkbenchSettings
from workbench.providers.tdx.live_members import fetch_live_board_members_cached
from workbench.query.market import MarketQueryService
from workbench.query.models import (
    CatalogMemberItem,
    MarketOverview,
    QueryMetadata,
    SearchResponse,
    SectorBreadthResponse,
    SectorCatalogMembersResponse,
    SectorListResponse,
    SectorMemberRankResponse,
    SectorRankResponse,
    SectorSnapshotResponse,
)
from workbench.query.sector_resolve import resolve_member_sector_id
from workbench.query.sectors import SectorQueryService
from workbench.services.collector_control import restart_collectors
from workbench.services.sector_groups import SectorGroupService, SectorGroupView
from workbench.services.stock_groups import StockGroupService, StockGroupView
from workbench.services.tdx_probe import probe_tdx_home
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore
from workbench.storage.workbench_config import append_settings_audit, read_settings_audit


def get_settings(request: Request) -> WorkbenchSettings:
    settings = getattr(request.app.state, "workbench_settings", None)
    if settings is None:
        return WorkbenchSettings()
    return settings


def get_meta_store(settings: WorkbenchSettings = Depends(get_settings)) -> MetaStore:
    store = MetaStore(settings.meta_db)
    store.initialize()
    return store


def get_hot_store(
    trade_date: date = Query(alias="date"),
    settings: WorkbenchSettings = Depends(get_settings),
) -> HotStore:
    path = settings.hot_db_for(trade_date.isoformat())
    if not path.is_file():
        raise HTTPException(status_code=404, detail="fund-flow data not found")
    store = HotStore(path)
    store.initialize()
    return store


def create_market_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/market", tags=["market"])

    @router.get("/overview", response_model=MarketOverview)
    def market_overview(
        trade_date: date = Query(alias="date"),
        minute: str | None = None,
        meta: MetaStore = Depends(get_meta_store),
        settings: WorkbenchSettings = Depends(get_settings),
    ) -> MarketOverview:
        hot = None
        hot_path = settings.hot_db_for(trade_date.isoformat())
        if hot_path.is_file():
            hot = HotStore(hot_path)
            hot.initialize()
        return MarketQueryService(meta, hot).overview(trade_date, minute)

    @router.get("/search", response_model=SearchResponse)
    def search(
        q: str = Query(min_length=1),
        meta: MetaStore = Depends(get_meta_store),
    ) -> SearchResponse:
        return MarketQueryService(meta).search(q)

    return router


class PrioritySectorsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_ids: list[str] = Field(default_factory=list)


class PriorityStocksPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbols: list[str] = Field(default_factory=list)


class LinkageSectorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str = ""
    sector_name: str = ""


class SyncHotTargetsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_sector_ids: list[str] = Field(default_factory=list)
    rank_sector_ids: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    linkage_sector_id: str = ""
    linkage_sector_name: str = ""


class CollectionTargetsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_ids: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)


class TdxProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tdx_home: str = Field(min_length=1)


class SectorGroupCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)


class SectorGroupRenamePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)


class SectorGroupMembersPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_ids: list[str] = Field(default_factory=list)


class SectorGroupActivePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    group_id: str = "all"


class SectorGroupMemberChartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chart_visible: bool


class StockGroupCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)


class StockGroupRenamePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)


class StockGroupMembersPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbols: list[str] = Field(default_factory=list)


class StockGroupActivePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    group_id: str = "all"


def _serialize_group(group: SectorGroupView) -> dict[str, object]:
    return {
        "id": group.id,
        "name": group.name,
        "sort_order": group.sort_order,
        "sector_ids": group.sector_ids,
        "sectors": [
            {
                "sector_id": member.sector_id,
                "name": member.name,
                "chart_visible": member.chart_visible,
            }
            for member in group.sectors
        ],
    }


def _serialize_sector_groups(service: SectorGroupService) -> dict[str, object]:
    return {
        "items": [_serialize_group(group) for group in service.list_groups()],
        "active_group_id": service.read_active_group_id(),
    }


def _serialize_stock_group(group: StockGroupView) -> dict[str, object]:
    return {
        "id": group.id,
        "name": group.name,
        "sort_order": group.sort_order,
        "symbol_ids": group.symbol_ids,
        "symbols": [
            {
                "symbol": member.symbol,
                "name": member.name,
            }
            for member in group.symbols
        ],
    }


def _serialize_stock_groups(service: StockGroupService) -> dict[str, object]:
    return {
        "items": [_serialize_stock_group(group) for group in service.list_groups()],
        "active_group_id": service.read_active_group_id(),
    }


def create_settings_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

    @router.put("/priority-sectors")
    def save_priority_sectors(
        payload: PrioritySectorsPayload,
        settings: WorkbenchSettings = Depends(get_settings),
    ) -> dict[str, object]:
        write_priority_sector_ids(settings.data_dir, payload.sector_ids)
        return {"ok": True, "count": len(payload.sector_ids)}

    @router.put("/priority-stocks")
    def save_priority_stocks(
        payload: PriorityStocksPayload,
        settings: WorkbenchSettings = Depends(get_settings),
    ) -> dict[str, object]:
        write_priority_stock_symbols(settings.data_dir, payload.symbols)
        return {"ok": True, "count": len(payload.symbols)}

    @router.put("/linkage-sector")
    def save_linkage_sector(
        payload: LinkageSectorPayload,
        settings: WorkbenchSettings = Depends(get_settings),
    ) -> dict[str, object]:
        write_linkage_sector_id(
            settings.data_dir,
            payload.sector_id or None,
            sector_name=payload.sector_name or None,
        )
        return {"ok": True, "sector_id": payload.sector_id}

    @router.put("/sync-hot-targets")
    def sync_hot_targets(
        payload: SyncHotTargetsPayload,
        request: Request,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        enhanced = None
        try:
            enhanced = get_hot_enhanced_client(request)
        except RuntimeError:
            enhanced = None
        selected_sector_ids = list(payload.selected_sector_ids)
        ui_path = settings.data_dir / "run" / "ui_selected_boards.json"
        if ui_path.is_file():
            try:
                ui_payload = json.loads(ui_path.read_text(encoding="utf-8"))
                ui_ids = [
                    str(item.get("id") or "").strip()
                    for item in ui_payload
                    if isinstance(item, dict) and str(item.get("id") or "").strip()
                ]
                # Prefer seeded/server watchlist whenever it differs and is non-empty.
                if ui_ids and ui_ids != selected_sector_ids:
                    selected_sector_ids = ui_ids
            except Exception:
                pass
        result = apply_hot_target_sync(
            settings,
            meta,
            selected_sector_ids=selected_sector_ids,
            rank_sector_ids=[] if len(selected_sector_ids) >= 80 else payload.rank_sector_ids,
            selected_stock_symbols=payload.symbols,
            linkage_sector_id=payload.linkage_sector_id or None,
            linkage_sector_name=payload.linkage_sector_name or None,
            enhanced_client=enhanced,
        )
        return {"ok": True, **result}

    @router.get("/collection-targets")
    def read_collection_targets(
        settings: WorkbenchSettings = Depends(get_settings),
        include_symbols: bool = Query(default=False),
    ) -> dict[str, object]:
        resolved_symbols = read_priority_stock_symbols(settings.data_dir)
        payload: dict[str, object] = {
            "sector_ids": read_priority_sector_ids(settings.data_dir),
            "manual_symbols": read_priority_manual_symbols(settings.data_dir),
            "resolved_symbol_count": len(resolved_symbols),
            "priority_max_sectors": settings.priority_max_sectors,
            "priority_max_stocks": settings.priority_max_stocks,
            "priority_sector_members": settings.priority_sector_members,
            "priority_linkage_members": settings.priority_linkage_members,
        }
        if include_symbols:
            payload["symbols"] = resolved_symbols
        return payload

    @router.get("/ui-selected-boards")
    def read_ui_selected_boards(
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        path = settings.data_dir / "run" / "ui_selected_boards.json"
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, list) and payload:
                    boards = [
                        {"id": str(item.get("id") or "").strip(), "name": str(item.get("name") or "").strip()}
                        for item in payload
                        if isinstance(item, dict) and str(item.get("id") or "").strip()
                    ]
                    return {"boards": boards, "source": "ui_selected_boards"}
            except Exception:
                pass
        sector_ids = read_priority_sector_ids(settings.data_dir)
        boards: list[dict[str, str]] = []
        with meta.connect() as connection:
            for sector_id in sector_ids:
                row = connection.execute(
                    "SELECT name FROM sector_master WHERE sector_id=?",
                    (sector_id,),
                ).fetchone()
                boards.append({"id": sector_id, "name": str(row[0]) if row else sector_id})
        return {"boards": boards, "source": "priority_sectors"}

    @router.put("/collection-targets")
    def save_collection_targets(
        payload: CollectionTargetsPayload,
        request: Request,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        sector_ids = payload.sector_ids[: settings.priority_max_sectors]
        manual_symbols = [symbol.upper() for symbol in payload.symbols]
        enhanced = None
        try:
            enhanced = get_hot_enhanced_client(request)
        except RuntimeError:
            enhanced = None
        resolved_symbols = resolve_priority_stock_symbols(
            meta,
            settings,
            sector_ids=sector_ids,
            linkage_sector_id=read_linkage_sector_id(settings.data_dir),
            linkage_sector_name=read_linkage_sector_name(settings.data_dir),
            manual_symbols=manual_symbols,
            enhanced_client=enhanced,
        )
        write_priority_sector_ids(settings.data_dir, sector_ids)
        write_priority_stock_targets(settings.data_dir, manual_symbols, resolved_symbols)
        append_settings_audit(
            settings.data_dir,
            "save_collection_targets",
            {
                "sector_count": len(sector_ids),
                "manual_symbol_count": len(manual_symbols),
                "resolved_symbol_count": len(resolved_symbols),
            },
        )
        return {
            "ok": True,
            "sector_count": len(read_priority_sector_ids(settings.data_dir)),
            "symbol_count": len(resolved_symbols),
            "manual_symbol_count": len(manual_symbols),
        }

    @router.post("/tdx-probe")
    def tdx_probe(payload: TdxProbeRequest) -> dict[str, object]:
        return probe_tdx_home(Path(payload.tdx_home))

    @router.post("/restart-collectors")
    def restart_collectors_endpoint(
        settings: WorkbenchSettings = Depends(get_settings),
    ) -> dict[str, object]:
        result = restart_collectors(settings.data_dir)
        append_settings_audit(settings.data_dir, "restart_collectors", result)
        return {"ok": True, **result}

    @router.get("/audit-log")
    def settings_audit_log(
        settings: WorkbenchSettings = Depends(get_settings),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, object]:
        return {"items": read_settings_audit(settings.data_dir, limit=limit)}

    @router.get("/sector-groups")
    def list_sector_groups(
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        return _serialize_sector_groups(SectorGroupService(meta))

    @router.post("/sector-groups")
    def create_sector_group(
        payload: SectorGroupCreatePayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = SectorGroupService(meta)
        group = service.create_group(payload.name)
        append_settings_audit(
            settings.data_dir,
            "create_sector_group",
            {"group_id": group.id, "name": group.name},
        )
        return {"ok": True, "group": _serialize_group(group)}

    @router.put("/sector-groups/active")
    def set_active_sector_group(
        payload: SectorGroupActivePayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = SectorGroupService(meta)
        try:
            active_group_id = service.set_active_group_id(payload.group_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(
            settings.data_dir,
            "set_active_sector_group",
            {"group_id": active_group_id},
        )
        return {"ok": True, "active_group_id": active_group_id}

    @router.put("/sector-groups/{group_id}")
    def rename_sector_group(
        group_id: str,
        payload: SectorGroupRenamePayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = SectorGroupService(meta)
        try:
            group = service.rename_group(group_id, payload.name)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(
            settings.data_dir,
            "rename_sector_group",
            {"group_id": group.id, "name": group.name},
        )
        return {"ok": True, "group": _serialize_group(group)}

    @router.delete("/sector-groups/{group_id}")
    def delete_sector_group(
        group_id: str,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = SectorGroupService(meta)
        try:
            service.delete_group(group_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(settings.data_dir, "delete_sector_group", {"group_id": group_id})
        return {"ok": True}

    @router.post("/sector-groups/{group_id}/members")
    def add_sector_group_members(
        group_id: str,
        payload: SectorGroupMembersPayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = SectorGroupService(meta)
        try:
            group = service.add_members(group_id, payload.sector_ids)
        except ValueError as error:
            message = str(error)
            status = 400 if "limit" in message else 404
            raise HTTPException(status_code=status, detail=message) from error
        append_settings_audit(
            settings.data_dir,
            "add_sector_group_members",
            {"group_id": group.id, "count": len(group.sector_ids)},
        )
        return {"ok": True, "group": _serialize_group(group)}

    @router.delete("/sector-groups/{group_id}/members/{sector_id}")
    def remove_sector_group_member(
        group_id: str,
        sector_id: str,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = SectorGroupService(meta)
        try:
            group = service.remove_member(group_id, sector_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(
            settings.data_dir,
            "remove_sector_group_member",
            {"group_id": group.id, "sector_id": sector_id},
        )
        return {"ok": True, "group": _serialize_group(group)}

    @router.put("/sector-groups/{group_id}/members/{sector_id}/chart-visible")
    def set_sector_group_member_chart_visible(
        group_id: str,
        sector_id: str,
        payload: SectorGroupMemberChartPayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = SectorGroupService(meta)
        try:
            group = service.set_member_chart_visible(group_id, sector_id, payload.chart_visible)
        except ValueError as error:
            message = str(error)
            status = 400 if "limit" in message else 404
            raise HTTPException(status_code=status, detail=message) from error
        append_settings_audit(
            settings.data_dir,
            "set_sector_group_member_chart_visible",
            {
                "group_id": group.id,
                "sector_id": sector_id,
                "chart_visible": payload.chart_visible,
            },
        )
        return {"ok": True, "group": _serialize_group(group)}

    @router.get("/stock-groups")
    def list_stock_groups(
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        return _serialize_stock_groups(StockGroupService(meta))

    @router.post("/stock-groups")
    def create_stock_group(
        payload: StockGroupCreatePayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = StockGroupService(meta)
        group = service.create_group(payload.name)
        append_settings_audit(
            settings.data_dir,
            "create_stock_group",
            {"group_id": group.id, "name": group.name},
        )
        return {"ok": True, "group": _serialize_stock_group(group)}

    @router.put("/stock-groups/active")
    def set_active_stock_group(
        payload: StockGroupActivePayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = StockGroupService(meta)
        try:
            active_group_id = service.set_active_group_id(payload.group_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(
            settings.data_dir,
            "set_active_stock_group",
            {"group_id": active_group_id},
        )
        return {"ok": True, "active_group_id": active_group_id}

    @router.put("/stock-groups/{group_id}")
    def rename_stock_group(
        group_id: str,
        payload: StockGroupRenamePayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = StockGroupService(meta)
        try:
            group = service.rename_group(group_id, payload.name)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(
            settings.data_dir,
            "rename_stock_group",
            {"group_id": group.id, "name": group.name},
        )
        return {"ok": True, "group": _serialize_stock_group(group)}

    @router.delete("/stock-groups/{group_id}")
    def delete_stock_group(
        group_id: str,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = StockGroupService(meta)
        try:
            service.delete_group(group_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(settings.data_dir, "delete_stock_group", {"group_id": group_id})
        return {"ok": True}

    @router.post("/stock-groups/{group_id}/members")
    def add_stock_group_members(
        group_id: str,
        payload: StockGroupMembersPayload,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = StockGroupService(meta)
        try:
            group = service.add_members(group_id, payload.symbols)
        except ValueError as error:
            message = str(error)
            status = 400 if "limit" in message else 404
            raise HTTPException(status_code=status, detail=message) from error
        append_settings_audit(
            settings.data_dir,
            "add_stock_group_members",
            {"group_id": group.id, "count": len(group.symbol_ids)},
        )
        return {"ok": True, "group": _serialize_stock_group(group)}

    @router.delete("/stock-groups/{group_id}/members/{symbol}")
    def remove_stock_group_member(
        group_id: str,
        symbol: str,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = StockGroupService(meta)
        try:
            group = service.remove_member(group_id, symbol)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        append_settings_audit(
            settings.data_dir,
            "remove_stock_group_member",
            {"group_id": group.id, "symbol": symbol.upper()},
        )
        return {"ok": True, "group": _serialize_stock_group(group)}

    return router


def create_sector_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/sectors", tags=["sectors"])

    @router.get("", response_model=SectorListResponse)
    def list_sectors(
        meta: MetaStore = Depends(get_meta_store),
        q: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1, le=1500),
    ) -> SectorListResponse:
        if q is not None or limit is not None:
            return SectorQueryService(meta).list_sectors(query=q, limit=limit or 50)
        return SectorQueryService(meta).list_sectors()

    @router.get("/rank", response_model=SectorRankResponse)
    def sector_rank(
        trade_date: date = Query(alias="date"),
        minute: str | None = None,
        limit: int = Query(default=12, ge=1, le=50),
        meta: MetaStore = Depends(get_meta_store),
        hot: HotStore = Depends(get_hot_store),
    ) -> SectorRankResponse:
        return SectorQueryService(meta, hot).sector_ranking(
            trade_date=trade_date.isoformat(),
            minute=minute,
            limit=limit,
        )

    @router.get("/snapshot", response_model=SectorSnapshotResponse)
    def sector_snapshot(
        trade_date: date = Query(alias="date"),
        minute: str = Query(default="15:00"),
        ids: str = Query(default=""),
        meta: MetaStore = Depends(get_meta_store),
        hot: HotStore = Depends(get_hot_store),
    ) -> SectorSnapshotResponse:
        sector_ids = [item.strip() for item in ids.split(",") if item.strip()]
        return SectorQueryService(meta, hot).sector_snapshot(
            sector_ids,
            trade_date=trade_date.isoformat(),
            minute=minute,
        )

    @router.get("/{sector_id}/catalog-members", response_model=SectorCatalogMembersResponse)
    def sector_catalog_members(
        sector_id: str,
        sector_name: str | None = Query(default=None, alias="name"),
        meta: MetaStore = Depends(get_meta_store),
    ) -> SectorCatalogMembersResponse:
        effective_sector_id = resolve_member_sector_id(
            meta,
            sector_id,
            sector_name=sector_name,
        )
        symbols = meta.memberships_for(effective_sector_id)
        names = meta.security_names(symbols)
        snapshot = meta.catalog_snapshot()
        return SectorCatalogMembersResponse(
            sector_id=effective_sector_id,
            items=[
                CatalogMemberItem(symbol=symbol, name=names.get(symbol, symbol))
                for symbol in symbols
            ],
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                source=snapshot.source,
                stale=snapshot.stale,
            ),
        )

    @router.get("/{sector_id}/members", response_model=SectorMemberRankResponse)
    def sector_members(
        sector_id: str,
        request: Request,
        trade_date: date = Query(alias="date"),
        minute: str = Query(default="09:31"),
        limit: int = Query(default=20, ge=1, le=100),
        sector_name: str | None = Query(default=None, alias="name"),
        meta: MetaStore = Depends(get_meta_store),
        hot: HotStore = Depends(get_hot_store),
    ) -> SectorMemberRankResponse:
        effective_sector_id = resolve_member_sector_id(
            meta,
            sector_id,
            sector_name=sector_name,
        )
        catalog_members = meta.memberships_for(effective_sector_id)

        live_members = None
        quote_client = None
        try:
            enhanced = get_hot_enhanced_client(request)
            quote_client = enhanced
            live_members = fetch_live_board_members_cached(
                enhanced,
                effective_sector_id,
                limit=limit,
                member_count=len(catalog_members) or None,
            )
        except (RuntimeError, OSError, ValueError, TypeError):
            live_members = None

        return SectorQueryService(meta, hot).member_ranking(
            effective_sector_id,
            trade_date=trade_date.isoformat(),
            minute=minute,
            limit=limit,
            live_members=live_members,
            quote_client=quote_client,
        )

    @router.get("/{sector_id}/breadth", response_model=SectorBreadthResponse)
    def sector_breadth(
        sector_id: str,
        trade_date: date = Query(alias="date"),
        minute: str = Query(default="09:31"),
        meta: MetaStore = Depends(get_meta_store),
        hot: HotStore = Depends(get_hot_store),
    ) -> SectorBreadthResponse:
        return SectorQueryService(meta, hot).member_breadth(
            sector_id,
            trade_date=trade_date.isoformat(),
            minute=minute,
        )

    return router
