from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path

from workbench.services.custom_sectors import (
    CUSTOM_SECTOR_SOURCE_DIRECTORY,
    MAX_CUSTOM_SECTOR_MEMBERS,
    CustomSectorService,
)
from workbench.services.stock_symbol_resolve import resolve_stock_symbols
from workbench.storage.meta_store import MetaStore

SUPPORTED_EXTENSIONS = {".txt", ".csv"}
_STOCK_CODE_PATTERN = re.compile(r"\b(\d{6})\b")


@dataclass(frozen=True)
class SyncFileResult:
    file_name: str
    sector_name: str
    sector_id: str
    member_count: int
    unresolved_count: int
    skipped: bool = False
    skip_reason: str | None = None


@dataclass(frozen=True)
class DeletedSectorResult:
    sector_name: str
    sector_id: str


@dataclass
class DirectorySyncResult:
    directory: str
    files_seen: int = 0
    sectors_updated: int = 0
    sectors_deleted: int = 0
    members_total: int = 0
    unresolved_total: int = 0
    managed_sector_names: list[str] = field(default_factory=list)
    files: list[SyncFileResult] = field(default_factory=list)
    deleted_sectors: list[DeletedSectorResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def sector_name_from_filename(filename: str) -> str:
    return Path(filename).stem.strip()


def parse_stock_codes_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    codes: list[str] = []
    for match in _STOCK_CODE_PATTERN.finditer(text):
        code = match.group(1)
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def normalize_directory_key(directory: Path) -> str:
    resolved = directory.expanduser()
    try:
        return str(resolved.resolve())
    except OSError:
        return str(resolved)


def list_sync_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda item: item.name.casefold())


class CustomSectorDirectorySyncService:
    def __init__(self, meta: MetaStore) -> None:
        self._meta = meta
        self._sector_service = CustomSectorService(meta)

    def sync_directory(
        self,
        directory: Path,
        *,
        previous_managed_names: list[str] | None = None,
    ) -> DirectorySyncResult:
        resolved_directory = directory.expanduser()
        directory_key = normalize_directory_key(resolved_directory)
        result = DirectorySyncResult(directory=directory_key)
        if not resolved_directory.is_dir():
            result.errors.append(f"directory not found: {resolved_directory}")
            return result

        files = list_sync_files(resolved_directory)
        result.files_seen = len(files)
        current_managed_names: set[str] = set()
        for file_path in files:
            sector_name = sector_name_from_filename(file_path.name)
            if sector_name:
                current_managed_names.add(sector_name)
            if not sector_name:
                result.files.append(
                    SyncFileResult(
                        file_name=file_path.name,
                        sector_name="",
                        sector_id="",
                        member_count=0,
                        unresolved_count=0,
                        skipped=True,
                        skip_reason="empty sector name",
                    )
                )
                continue
            try:
                text = file_path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError as error:
                result.errors.append(f"{file_path.name}: {error}")
                continue

            raw_codes = parse_stock_codes_from_text(text)
            resolve_result = resolve_stock_symbols(self._meta, raw_codes)
            resolved_symbols = [
                str(item["symbol"]).upper()
                for item in resolve_result.get("resolved", [])
                if isinstance(item, dict) and item.get("symbol")
            ]
            unresolved_count = len(resolve_result.get("unresolved", []))
            if len(resolved_symbols) > MAX_CUSTOM_SECTOR_MEMBERS:
                result.files.append(
                    SyncFileResult(
                        file_name=file_path.name,
                        sector_name=sector_name,
                        sector_id="",
                        member_count=0,
                        unresolved_count=unresolved_count,
                        skipped=True,
                        skip_reason=f"member limit is {MAX_CUSTOM_SECTOR_MEMBERS}",
                    )
                )
                result.errors.append(
                    f"{file_path.name}: resolved {len(resolved_symbols)} symbols, exceeds limit"
                )
                continue

            sector = self._sector_service.upsert_sector_by_name(
                sector_name,
                source_type=CUSTOM_SECTOR_SOURCE_DIRECTORY,
            )
            updated = self._sector_service.set_members(sector.sector_id, resolved_symbols)
            result.sectors_updated += 1
            result.members_total += len(updated.symbols)
            result.unresolved_total += unresolved_count
            result.files.append(
                SyncFileResult(
                    file_name=file_path.name,
                    sector_name=sector_name,
                    sector_id=updated.sector_id,
                    member_count=len(updated.symbols),
                    unresolved_count=unresolved_count,
                )
            )

        previous_names = set(previous_managed_names or [])
        for sector_name in sorted(previous_names - current_managed_names):
            sector = self._sector_service.find_sector_by_name(sector_name)
            if sector is None:
                continue
            self._sector_service.delete_sector(sector.sector_id)
            result.sectors_deleted += 1
            result.deleted_sectors.append(
                DeletedSectorResult(sector_name=sector_name, sector_id=sector.sector_id)
            )

        result.managed_sector_names = sorted(current_managed_names)
        return result
