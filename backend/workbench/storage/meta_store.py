from __future__ import annotations

import sqlite3
from pathlib import Path

from workbench.domain import Membership, Sector, Security
from workbench.storage.schema import META_SCHEMA


class MetaStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(META_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES('retention_days', '30')"
            )

    def replace_catalog(
        self,
        *,
        securities: list[Security],
        sectors: list[Sector],
        memberships: list[Membership],
        version: str,
    ) -> None:
        with self.connect() as connection:
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
                "INSERT INTO catalog_state(singleton, version) VALUES(1, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET version=excluded.version",
                (version,),
            )

    def security_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM security_master").fetchone()[0])

    def sector_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM sector_master").fetchone()[0])

    def memberships_for(self, sector_id: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT symbol FROM sector_membership WHERE sector_id=? ORDER BY symbol",
                (sector_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def all_memberships(self) -> list[Membership]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT sector_id, symbol FROM sector_membership ORDER BY sector_id, symbol"
            ).fetchall()
        return [Membership(sector_id=row[0], symbol=row[1]) for row in rows]

    def catalog_version(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT version FROM catalog_state WHERE singleton=1").fetchone()
        return str(row[0]) if row else None

    def retention_days(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='retention_days'"
            ).fetchone()
        return int(row[0]) if row else 30

    def set_retention_days(self, days: int) -> None:
        if not 1 <= days <= 2500:
            raise ValueError("retention days must be between 1 and 2500")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES('retention_days', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(days),),
            )
