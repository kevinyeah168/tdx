from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_SYNC_INTERVAL_SECONDS = 60
MIN_SYNC_INTERVAL_SECONDS = 30
MAX_SYNC_INTERVAL_SECONDS = 600


class CustomSectorSyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    directory_path: str = ""
    auto_sync_enabled: bool = False
    interval_seconds: int = Field(default=DEFAULT_SYNC_INTERVAL_SECONDS)
    last_sync_at: str | None = None
    last_sync_error: str | None = None
    last_sync_summary: dict[str, object] | None = None
    managed_directory_path: str = ""
    managed_sector_names: list[str] = Field(default_factory=list)

    @field_validator("directory_path")
    @classmethod
    def _strip_directory_path(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("interval_seconds")
    @classmethod
    def _clamp_interval(cls, value: int) -> int:
        return max(MIN_SYNC_INTERVAL_SECONDS, min(MAX_SYNC_INTERVAL_SECONDS, int(value)))


def custom_sector_sync_config_path(data_dir: Path) -> Path:
    return data_dir / "run" / "custom_sector_sync.json"


def read_custom_sector_sync_config(data_dir: Path) -> CustomSectorSyncConfig:
    path = custom_sector_sync_config_path(data_dir)
    if not path.is_file():
        return CustomSectorSyncConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CustomSectorSyncConfig()
    try:
        return CustomSectorSyncConfig.model_validate(payload)
    except ValueError:
        return CustomSectorSyncConfig()


def write_custom_sector_sync_config(
    data_dir: Path,
    config: CustomSectorSyncConfig,
) -> CustomSectorSyncConfig:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    custom_sector_sync_config_path(data_dir).write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config


def record_custom_sector_sync_result(
    data_dir: Path,
    *,
    summary: dict[str, object] | None = None,
    error: str | None = None,
    managed_directory_path: str | None = None,
    managed_sector_names: list[str] | None = None,
) -> CustomSectorSyncConfig:
    config = read_custom_sector_sync_config(data_dir)
    updates: dict[str, object] = {
        "last_sync_at": datetime.now().isoformat(timespec="seconds"),
        "last_sync_error": error,
        "last_sync_summary": summary,
    }
    if managed_directory_path is not None:
        updates["managed_directory_path"] = managed_directory_path
    if managed_sector_names is not None:
        updates["managed_sector_names"] = managed_sector_names
    updated = config.model_copy(update=updates)
    return write_custom_sector_sync_config(data_dir, updated)
