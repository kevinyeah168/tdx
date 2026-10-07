from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class LimitUpSnapshotStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_up_daily_snapshot (
                    trade_date TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

    def get(self, trade_date: str) -> dict | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT payload_json FROM limit_up_daily_snapshot WHERE trade_date = ?",
                (trade_date,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        if not isinstance(payload, dict):
            return None
        return payload

    def save(self, trade_date: str, payload: dict, *, fetched_at: str) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO limit_up_daily_snapshot (trade_date, payload_json, fetched_at, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(trade_date) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    updated_at = datetime('now')
                """,
                (trade_date, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), fetched_at),
            )

    @contextmanager
    def _session(self):
        connection = sqlite3.connect(self._db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()
