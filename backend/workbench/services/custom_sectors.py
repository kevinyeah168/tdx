from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from workbench.query.custom_sector_ids import (
    CUSTOM_SECTOR_PREFIX,
    CUSTOM_SECTOR_TYPE,
    is_custom_sector_id,
)
from workbench.storage.meta_store import MetaStore

MAX_CUSTOM_SECTOR_MEMBERS = 60
CUSTOM_SECTOR_SOURCE_MANUAL = "manual"
CUSTOM_SECTOR_SOURCE_DIRECTORY = "directory"


@dataclass(frozen=True)
class CustomSectorMember:
    symbol: str
    name: str


@dataclass(frozen=True)
class CustomSectorView:
    sector_id: str
    name: str
    sort_order: int
    source_type: str
    symbols: list[str]
    members: list[CustomSectorMember]


def _new_sector_id() -> str:
    return f"{CUSTOM_SECTOR_PREFIX}{uuid.uuid4().hex[:12]}"


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()


class CustomSectorService:
    def __init__(self, meta: MetaStore) -> None:
        self._meta = meta

    def ensure_schema(self) -> None:
        with self._meta._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS custom_sector (
                    sector_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS custom_sector_member (
                    sector_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (sector_id, symbol),
                    FOREIGN KEY (sector_id) REFERENCES custom_sector(sector_id) ON DELETE CASCADE
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(custom_sector)").fetchall()
            }
            if "source_type" not in columns:
                connection.execute(
                    "ALTER TABLE custom_sector ADD COLUMN source_type TEXT NOT NULL DEFAULT 'manual'"
                )

    def list_sectors(self) -> list[CustomSectorView]:
        self.ensure_schema()
        with self._meta._session() as connection:
            sector_rows = connection.execute(
                "SELECT sector_id, name, sort_order, source_type FROM custom_sector ORDER BY sort_order, created_at"
            ).fetchall()
            member_rows = connection.execute(
                "SELECT sector_id, symbol, sort_order FROM custom_sector_member ORDER BY sort_order, symbol"
            ).fetchall()
            stock_names = {
                str(row[0]).upper(): str(row[1])
                for row in connection.execute("SELECT symbol, name FROM security_master").fetchall()
            }
        members_by_sector: dict[str, list[tuple[str, int]]] = {}
        for sector_id, symbol, sort_order in member_rows:
            members_by_sector.setdefault(str(sector_id), []).append(
                (_normalize_symbol(symbol), int(sort_order))
            )
        views: list[CustomSectorView] = []
        for sector_id, name, sort_order, source_type in sector_rows:
            sid = str(sector_id)
            ordered = sorted(members_by_sector.get(sid, []), key=lambda item: (item[1], item[0]))
            symbol_ids = [symbol for symbol, _ in ordered]
            views.append(
                CustomSectorView(
                    sector_id=sid,
                    name=str(name),
                    sort_order=int(sort_order),
                    source_type=str(source_type or CUSTOM_SECTOR_SOURCE_MANUAL),
                    symbols=symbol_ids,
                    members=[
                        CustomSectorMember(
                            symbol=symbol,
                            name=stock_names.get(symbol, symbol),
                        )
                        for symbol in symbol_ids
                    ],
                )
            )
        return views

    def sector_names(self) -> dict[str, str]:
        return {sector.sector_id: sector.name for sector in self.list_sectors()}

    def exists(self, sector_id: str) -> bool:
        if not is_custom_sector_id(sector_id):
            return False
        self.ensure_schema()
        with self._meta._session() as connection:
            row = connection.execute(
                "SELECT 1 FROM custom_sector WHERE sector_id=?",
                (sector_id,),
            ).fetchone()
        return row is not None

    def symbols_for(self, sector_id: str) -> list[str]:
        for sector in self.list_sectors():
            if sector.sector_id == sector_id:
                return list(sector.symbols)
        return []

    def get_sector(self, sector_id: str) -> CustomSectorView:
        for sector in self.list_sectors():
            if sector.sector_id == sector_id:
                return sector
        raise ValueError("custom sector not found")

    def find_sector_by_name(self, name: str) -> CustomSectorView | None:
        cleaned = name.strip()
        if not cleaned:
            return None
        for sector in self.list_sectors():
            if sector.name == cleaned:
                return sector
        return None

    def upsert_sector_by_name(
        self,
        name: str,
        *,
        source_type: str = CUSTOM_SECTOR_SOURCE_MANUAL,
    ) -> CustomSectorView:
        existing = self.find_sector_by_name(name)
        if existing is not None:
            if existing.source_type != source_type:
                self.set_source_type(existing.sector_id, source_type)
                return self.get_sector(existing.sector_id)
            return existing
        return self.create_sector(name, source_type=source_type)

    def set_source_type(self, sector_id: str, source_type: str) -> None:
        self.ensure_schema()
        self.get_sector(sector_id)
        with self._meta._session() as connection:
            connection.execute(
                "UPDATE custom_sector SET source_type=? WHERE sector_id=?",
                (source_type, sector_id),
            )

    def create_sector(
        self,
        name: str,
        *,
        source_type: str = CUSTOM_SECTOR_SOURCE_MANUAL,
    ) -> CustomSectorView:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("sector name must not be blank")
        self.ensure_schema()
        sector_id = _new_sector_id()
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._meta._session() as connection:
            sort_order = int(connection.execute("SELECT COUNT(*) FROM custom_sector").fetchone()[0])
            connection.execute(
                "INSERT INTO custom_sector(sector_id, name, sort_order, created_at, source_type) VALUES(?, ?, ?, ?, ?)",
                (sector_id, cleaned, sort_order, created_at, source_type),
            )
        return self.get_sector(sector_id)

    def rename_sector(self, sector_id: str, name: str) -> CustomSectorView:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("sector name must not be blank")
        self.ensure_schema()
        with self._meta._session() as connection:
            cursor = connection.execute(
                "UPDATE custom_sector SET name=? WHERE sector_id=?",
                (cleaned, sector_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("custom sector not found")
        return self.get_sector(sector_id)

    def delete_sector(self, sector_id: str) -> None:
        self.ensure_schema()
        with self._meta._session() as connection:
            cursor = connection.execute("DELETE FROM custom_sector WHERE sector_id=?", (sector_id,))
            if cursor.rowcount == 0:
                raise ValueError("custom sector not found")

    def add_members(self, sector_id: str, symbols: list[str]) -> CustomSectorView:
        self.ensure_schema()
        self.get_sector(sector_id)
        normalized: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            code = _normalize_symbol(symbol)
            if not code or code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        if not normalized:
            return self.get_sector(sector_id)
        with self._meta._session() as connection:
            existing = {
                str(row[0]).upper()
                for row in connection.execute(
                    "SELECT symbol FROM custom_sector_member WHERE sector_id=?",
                    (sector_id,),
                ).fetchall()
            }
            new_members = [symbol for symbol in normalized if symbol not in existing]
            if len(existing) + len(new_members) > MAX_CUSTOM_SECTOR_MEMBERS:
                raise ValueError(f"custom sector member limit is {MAX_CUSTOM_SECTOR_MEMBERS}")
            next_order = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) FROM custom_sector_member WHERE sector_id=?",
                    (sector_id,),
                ).fetchone()[0]
            )
            for symbol in new_members:
                next_order += 1
                connection.execute(
                    "INSERT INTO custom_sector_member(sector_id, symbol, sort_order) VALUES(?, ?, ?)",
                    (sector_id, symbol, next_order),
                )
        return self.get_sector(sector_id)

    def remove_member(self, sector_id: str, symbol: str) -> CustomSectorView:
        self.ensure_schema()
        with self._meta._session() as connection:
            connection.execute(
                "DELETE FROM custom_sector_member WHERE sector_id=? AND symbol=?",
                (sector_id, _normalize_symbol(symbol)),
            )
        return self.get_sector(sector_id)

    def set_members(self, sector_id: str, symbols: list[str]) -> CustomSectorView:
        self.ensure_schema()
        self.get_sector(sector_id)
        normalized: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            code = _normalize_symbol(symbol)
            if not code or code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        if len(normalized) > MAX_CUSTOM_SECTOR_MEMBERS:
            raise ValueError(f"custom sector member limit is {MAX_CUSTOM_SECTOR_MEMBERS}")
        with self._meta._session() as connection:
            connection.execute(
                "DELETE FROM custom_sector_member WHERE sector_id=?",
                (sector_id,),
            )
            for index, symbol in enumerate(normalized):
                connection.execute(
                    "INSERT INTO custom_sector_member(sector_id, symbol, sort_order) VALUES(?, ?, ?)",
                    (sector_id, symbol, index),
                )
        return self.get_sector(sector_id)
