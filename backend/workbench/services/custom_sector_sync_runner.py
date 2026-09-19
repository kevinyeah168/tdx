from __future__ import annotations

import asyncio
from pathlib import Path

from workbench.config import WorkbenchSettings
from workbench.services.custom_sector_directory_sync import (
    CustomSectorDirectorySyncService,
    normalize_directory_key,
)
from workbench.storage.custom_sector_sync_config import (
    MIN_SYNC_INTERVAL_SECONDS,
    read_custom_sector_sync_config,
    record_custom_sector_sync_result,
)
from workbench.storage.meta_store import MetaStore


def _serialize_sync_result(result) -> dict[str, object]:
    return {
        "directory": result.directory,
        "files_seen": result.files_seen,
        "sectors_updated": result.sectors_updated,
        "sectors_deleted": result.sectors_deleted,
        "members_total": result.members_total,
        "managed_sector_names": result.managed_sector_names,
        "deleted_sectors": [
            {
                "sector_name": item.sector_name,
                "sector_id": item.sector_id,
            }
            for item in result.deleted_sectors
        ],
        "unresolved_total": result.unresolved_total,
        "errors": result.errors,
        "files": [
            {
                "file_name": item.file_name,
                "sector_name": item.sector_name,
                "sector_id": item.sector_id,
                "member_count": item.member_count,
                "unresolved_count": item.unresolved_count,
                "skipped": item.skipped,
                "skip_reason": item.skip_reason,
            }
            for item in result.files
        ],
    }


def run_custom_sector_directory_sync(
    settings: WorkbenchSettings,
    *,
    directory: str | None = None,
) -> dict[str, object]:
    config = read_custom_sector_sync_config(settings.data_dir)
    target = (directory or config.directory_path).strip()
    if not target:
        raise ValueError("directory path must not be blank")

    target_path = Path(target)
    target_key = normalize_directory_key(target_path)
    managed_key = (
        normalize_directory_key(Path(config.managed_directory_path))
        if config.managed_directory_path
        else ""
    )
    previous_managed_names = (
        list(config.managed_sector_names) if managed_key == target_key else []
    )

    meta = MetaStore(settings.meta_db)
    meta.initialize()
    service = CustomSectorDirectorySyncService(meta)
    result = service.sync_directory(
        target_path,
        previous_managed_names=previous_managed_names,
    )
    summary = _serialize_sync_result(result)
    error = "; ".join(result.errors) if result.errors else None
    record_custom_sector_sync_result(
        settings.data_dir,
        summary=summary,
        error=error,
        managed_directory_path=target_key,
        managed_sector_names=result.managed_sector_names,
    )
    return summary


async def custom_sector_sync_loop(settings: WorkbenchSettings) -> None:
    while True:
        config = read_custom_sector_sync_config(settings.data_dir)
        sleep_seconds = max(MIN_SYNC_INTERVAL_SECONDS, config.interval_seconds)
        if config.auto_sync_enabled and config.directory_path.strip():
            try:
                await asyncio.to_thread(run_custom_sector_directory_sync, settings)
            except Exception as error:
                record_custom_sector_sync_result(
                    settings.data_dir,
                    summary=None,
                    error=str(error),
                )
        await asyncio.sleep(sleep_seconds)
