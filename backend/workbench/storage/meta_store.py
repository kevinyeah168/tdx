from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from workbench.domain import Membership, Sector, Security
from workbench.storage.schema import META_SCHEMA


@dataclass(frozen=True)
class CatalogSnapshot:
    memberships: tuple[Membership, ...]
    sector_count: int
    catalog_version: str | None
    synced_at: str | None = None
    source: str | None = None
    stale: bool = False
    error_summary: str | None = None


class MetaStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._session() as connection:
            connection.executescript(META_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES('retention_days', '365')"
            )
            self._migrate_catalog_state(connection)

    def _migrate_catalog_state(self, connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(catalog_state)").fetchall()
        }
        if "synced_at" not in columns:
            connection.execute("ALTER TABLE catalog_state ADD COLUMN synced_at TEXT")
        if "source" not in columns:
            connection.execute(
                "ALTER TABLE catalog_state ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'"
            )
        if "stale" not in columns:
            connection.execute(
                "ALTER TABLE catalog_state ADD COLUMN stale INTEGER NOT NULL DEFAULT 0"
            )
        if "error_summary" not in columns:
            connection.execute("ALTER TABLE catalog_state ADD COLUMN error_summary TEXT")

    def replace_catalog(
        self,
        *,
        securities: list[Security],
        sectors: list[Sector],
        memberships: list[Membership],
        version: str,
        synced_at: str | None = None,
        source: str = "unknown",
        stale: bool = False,
        error_summary: str | None = None,
    ) -> None:
        with self._session() as connection:
            connection.execute("DELETE FROM sector_membership")
            connection.execute("DELETE FROM sector_master")
            connection.execute("DELETE FROM security_master")
            connection.executemany(
                "INSERT INTO security_master VALUES(?, ?, ?, ?, ?)",
                [(s.symbol, s.code, s.name, s.market, int(s.active)) for s in securities],
            )
            connection.executemany(
                "INSERT INTO sector_master VALUES(?, ?, ?)",
                [(s.sector_id, s.name, s.sector_type) for s in sectors],
            )
            connection.executemany(
                "INSERT INTO sector_membership VALUES(?, ?)",
                [(m.sector_id, m.symbol) for m in memberships],
            )
            connection.execute(
                "INSERT INTO catalog_state("
                "singleton, version, synced_at, source, stale, error_summary"
                ") VALUES(1, ?, ?, ?, ?, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET "
                "version=excluded.version, "
                "synced_at=excluded.synced_at, "
                "source=excluded.source, "
                "stale=excluded.stale, "
                "error_summary=excluded.error_summary",
                (version, synced_at, source, int(stale), error_summary),
            )

    def mark_catalog_stale(self, *, error_summary: str, source: str = "unknown") -> None:
        with self._session() as connection:
            connection.execute(
                "UPDATE catalog_state SET stale=1, error_summary=?, source=? WHERE singleton=1",
                (error_summary, source),
            )

    def security_count(self) -> int:
        with self._session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM security_master").fetchone()[0])

    def sector_count(self) -> int:
        with self._session() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM sector_master").fetchone()[0])

    def memberships_for(self, sector_id: str) -> list[str]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT symbol FROM sector_membership WHERE sector_id=? ORDER BY symbol",
                (sector_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def all_memberships(self) -> list[Membership]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT sector_id, symbol FROM sector_membership ORDER BY sector_id, symbol"
            ).fetchall()
        return [Membership(sector_id=row[0], symbol=row[1]) for row in rows]

    def catalog_snapshot(self) -> CatalogSnapshot:
        with self._session() as connection:
            connection.execute("BEGIN")
            memberships = tuple(
                Membership(sector_id=row[0], symbol=row[1])
                for row in connection.execute(
                    "SELECT sector_id, symbol FROM sector_membership ORDER BY sector_id, symbol"
                ).fetchall()
            )
            sector_count = int(connection.execute("SELECT COUNT(*) FROM sector_master").fetchone()[0])
            row = connection.execute(
                "SELECT version, synced_at, source, stale, error_summary "
                "FROM catalog_state WHERE singleton=1"
            ).fetchone()
        return CatalogSnapshot(
            memberships=memberships,
            sector_count=sector_count,
            catalog_version=str(row[0]) if row else None,
            synced_at=str(row[1]) if row and row[1] is not None else None,
            source=str(row[2]) if row and row[2] is not None else None,
            stale=bool(row[3]) if row else False,
            error_summary=str(row[4]) if row and row[4] is not None else None,
        )

    def catalog_version(self) -> str | None:
        with self._session() as connection:
            row = connection.execute("SELECT version FROM catalog_state WHERE singleton=1").fetchone()
        return str(row[0]) if row else None

    def retention_days(self) -> int:
        with self._session() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='retention_days'"
            ).fetchone()
        return int(row[0]) if row else 30

    def set_retention_days(self, days: int) -> None:
        if type(days) is not int or not 1 <= days <= 2500:
            raise ValueError("retention days must be between 1 and 2500")
        with self._session() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES('retention_days', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(days),),
            )

    def security_names(self, symbols: list[str]) -> dict[str, str]:
        if not symbols:
            return {}
        unique = list(dict.fromkeys(symbols))
        placeholders = ",".join("?" for _ in unique)
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT symbol, name FROM security_master WHERE symbol IN ({placeholders})",
                unique,
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}
