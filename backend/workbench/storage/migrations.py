from __future__ import annotations

import sqlite3

HOT_SCHEMA_VERSION = 1


def ensure_hot_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='collection_status'"
    ).fetchone()
    if row is None:
        return
    columns = {
        str(item[1])
        for item in connection.execute("PRAGMA table_info(collection_status)").fetchall()
    }
    if "algorithm_version" not in columns:
        connection.execute(
            "ALTER TABLE collection_status ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'v1'"
        )
