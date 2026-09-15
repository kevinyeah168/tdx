from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workbench.config import WorkbenchSettings
from workbench.query.stocks import ReplayQueryService
from workbench.services.tdx_probe import probe_tdx_home
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore
from workbench.storage.workbench_config import (
    append_settings_audit,
    read_workbench_user_config,
    write_workbench_user_config,
)


def get_settings(request: Request) -> WorkbenchSettings:
    settings = getattr(request.app.state, "workbench_settings", None)
    if settings is None:
        return WorkbenchSettings()
    return settings


def get_meta_store(settings: WorkbenchSettings = Depends(get_settings)) -> MetaStore:
    store = MetaStore(settings.meta_db)
    store.initialize()
    return store


def get_optional_hot_store(
    trade_date: date | None = Query(default=None, alias="date"),
    settings: WorkbenchSettings = Depends(get_settings),
) -> HotStore | None:
    if trade_date is None:
        return None
    path = settings.hot_db_for(trade_date.isoformat())
    if not path.is_file():
        return None
    store = HotStore(path)
    store.initialize()
    return store


class TdxProbeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    vipdoc_ok: bool = False
    tnf_ok: bool = False
    mac_reachable: bool = False
    client_likely_running: bool = False
    ok: bool = False


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    retention_days: int = Field(ge=1, le=2500)
    tdx_home: str
    collect_mode: Literal["selective", "full"]
    archive_full_enabled: bool
    priority_max_sectors: int = Field(ge=1, le=2000)
    priority_max_stocks: int = Field(ge=1, le=50000)
    priority_sector_members: int = Field(ge=1, le=10000)
    priority_linkage_members: int = Field(ge=1, le=10000)
    tdx_probe: TdxProbeSummary | None = None


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    retention_days: int | None = Field(default=None, ge=1, le=2500)
    tdx_home: str | None = None
    collect_mode: Literal["selective", "full"] | None = None
    archive_full_enabled: bool | None = None


def _build_settings_payload(
    settings: WorkbenchSettings,
    meta: MetaStore,
    *,
    include_probe: bool = False,
) -> SettingsPayload:
    user_cfg = read_workbench_user_config(settings.data_dir)
    probe = None
    if include_probe:
        raw = probe_tdx_home(Path(user_cfg.tdx_home))
        probe = TdxProbeSummary(
            vipdoc_ok=bool(raw.get("vipdoc_ok")),
            tnf_ok=bool(raw.get("tnf_ok")),
            mac_reachable=bool(raw.get("mac_reachable")),
            client_likely_running=bool(raw.get("client_likely_running")),
            ok=bool(raw.get("ok")),
        )
    return SettingsPayload(
        retention_days=meta.retention_days(),
        tdx_home=user_cfg.tdx_home,
        collect_mode=user_cfg.collect_mode,
        archive_full_enabled=user_cfg.archive_full_enabled,
        priority_max_sectors=settings.priority_max_sectors,
        priority_max_stocks=settings.priority_max_stocks,
        priority_sector_members=settings.priority_sector_members,
        priority_linkage_members=settings.priority_linkage_members,
        tdx_probe=probe,
    )


def create_replay_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["replay"])

    @router.get("/replay/dates")
    def replay_dates(
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> dict[str, object]:
        service = ReplayQueryService(settings.data_dir, meta)
        return {"dates": service.available_dates()}

    @router.get("/replay/minutes")
    def replay_minutes(
        trade_date: date = Query(alias="date"),
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
        hot: HotStore | None = Depends(get_optional_hot_store),
    ) -> dict[str, object]:
        if hot is None:
            raise HTTPException(status_code=404, detail="trade date not found")
        service = ReplayQueryService(settings.data_dir, meta, hot)
        minutes = service.complete_minutes(trade_date.isoformat())
        if not minutes:
            raise HTTPException(status_code=404, detail="no complete minutes")
        return {
            "trade_date": trade_date.isoformat(),
            "minutes": minutes,
            "latest_complete_minute": service.latest_complete_minute(trade_date.isoformat()),
            "latest_sector_minute": service.latest_sector_minute(trade_date.isoformat()),
            "latest_stock_minute": service.latest_stock_minute(trade_date.isoformat()),
            "latest_available_minute": service.latest_available_minute(trade_date.isoformat()),
        }

    @router.get("/settings", response_model=SettingsPayload)
    def read_settings(
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
        probe: bool = Query(default=True),
    ) -> SettingsPayload:
        return _build_settings_payload(settings, meta, include_probe=probe)

    @router.put("/settings", response_model=SettingsPayload)
    def update_settings(
        payload: SettingsUpdateRequest,
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
    ) -> SettingsPayload:
        user_cfg = read_workbench_user_config(settings.data_dir)
        changed: dict[str, object] = {}
        if payload.retention_days is not None:
            meta.set_retention_days(payload.retention_days)
            changed["retention_days"] = payload.retention_days
        if payload.tdx_home is not None:
            user_cfg = user_cfg.model_copy(update={"tdx_home": payload.tdx_home.strip()})
            changed["tdx_home"] = user_cfg.tdx_home
        if payload.collect_mode is not None:
            user_cfg = user_cfg.model_copy(update={"collect_mode": payload.collect_mode})
            if payload.collect_mode == "full" and payload.archive_full_enabled is None:
                user_cfg = user_cfg.model_copy(update={"archive_full_enabled": True})
            if payload.collect_mode == "selective" and payload.archive_full_enabled is None:
                user_cfg = user_cfg.model_copy(update={"archive_full_enabled": False})
            changed["collect_mode"] = payload.collect_mode
        if payload.archive_full_enabled is not None:
            user_cfg = user_cfg.model_copy(update={"archive_full_enabled": payload.archive_full_enabled})
            changed["archive_full_enabled"] = payload.archive_full_enabled
        if any(key != "retention_days" for key in changed):
            write_workbench_user_config(settings.data_dir, user_cfg)
        if changed:
            append_settings_audit(settings.data_dir, "update_settings", changed)
        return _build_settings_payload(settings, meta, include_probe=True)

    @router.get("/health/detail")
    def health_detail(
        settings: WorkbenchSettings = Depends(get_settings),
        meta: MetaStore = Depends(get_meta_store),
        hot: HotStore | None = Depends(get_optional_hot_store),
    ) -> dict[str, object]:
        return ReplayQueryService(settings.data_dir, meta, hot).health()

    return router
