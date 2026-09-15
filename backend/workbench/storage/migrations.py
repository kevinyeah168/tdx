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
        try:
            connection.execute(
                "ALTER TABLE collection_status ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'v1'"
            )
        except sqlite3.OperationalError as error:
            if "duplicate column" not in str(error).lower():
                raise
    gray_table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_gray_minute'"
    ).fetchone()
    if gray_table is None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS stock_gray_minute (
                trade_date TEXT NOT NULL,
                minute TEXT NOT NULL,
                symbol TEXT NOT NULL,
                code TEXT NOT NULL,
                open_cum REAL NOT NULL,
                dark_cum REAL NOT NULL,
                total_cum REAL NOT NULL,
                observed_at TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (trade_date, minute, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_stock_gray_series
            ON stock_gray_minute(trade_date, symbol, minute);
            """
        )
