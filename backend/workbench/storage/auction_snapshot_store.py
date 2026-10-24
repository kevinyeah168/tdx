from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from workbench.collector.trading_clock import AUCTION_BOARD_DEFAULT_SORT, AUCTION_BOARD_SORT_KEYS

_SORT_COLUMNS: dict[str, str] = {
    "ratio": "volume_ratio",
    "amount": "amount",
    "change": "change_pct",
    "volume": "volume",
    "price": "price",
}


class AuctionSnapshotStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auction_daily_snapshot (
                    trade_date TEXT NOT NULL,
                    sort_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (trade_date, sort_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auction_day_meta (
                    trade_date TEXT NOT NULL PRIMARY KEY,
                    fetched_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auction_stock_row (
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price REAL,
                    change_pct REAL,
                    volume_ratio REAL,
                    amount REAL,
                    volume REAL,
                    open_net_inflow REAL,
                    PRIMARY KEY (trade_date, symbol)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_auction_stock_row_trade_code
                ON auction_stock_row (trade_date, code)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_auction_stock_row_trade_name
                ON auction_stock_row (trade_date, name)
                """
            )

    def get(self, trade_date: str, sort_key: str) -> dict | None:
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM auction_daily_snapshot
                WHERE trade_date = ? AND sort_key = ?
                """,
                (trade_date, sort_key),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        if not isinstance(payload, dict):
            return None
        return payload

    def save(self, trade_date: str, sort_key: str, payload: dict, *, fetched_at: str) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO auction_daily_snapshot (trade_date, sort_key, payload_json, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(trade_date, sort_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    updated_at = datetime('now')
                """,
                (
                    trade_date,
                    sort_key,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    fetched_at,
                ),
            )

    def has_stock_rows(self, trade_date: str) -> bool:
        with self._session() as connection:
            row = connection.execute(
                "SELECT 1 FROM auction_stock_row WHERE trade_date = ? LIMIT 1",
                (trade_date,),
            ).fetchone()
        return row is not None

    def get_day_meta(self, trade_date: str) -> dict[str, Any] | None:
        with self._session() as connection:
            row = connection.execute(
                """
                SELECT fetched_at, source, total_count
                FROM auction_day_meta
                WHERE trade_date = ?
                """,
                (trade_date,),
            ).fetchone()
        if row is None:
            return None
        return {
            "fetched_at": str(row[0]),
            "source": str(row[1]),
            "total_count": int(row[2]),
        }

    def replace_stock_rows(
        self,
        trade_date: str,
        rows: list[dict[str, Any]],
        *,
        fetched_at: str,
        source: str,
    ) -> int:
        with self._session() as connection:
            connection.execute("DELETE FROM auction_stock_row WHERE trade_date = ?", (trade_date,))
            if rows:
                connection.executemany(
                    """
                    INSERT INTO auction_stock_row (
                        trade_date, symbol, code, name, price, change_pct,
                        volume_ratio, amount, volume, open_net_inflow
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            trade_date,
                            str(row["symbol"]),
                            str(row["code"]),
                            str(row["name"]),
                            row.get("price"),
                            row.get("change_pct"),
                            row.get("volume_ratio"),
                            row.get("amount"),
                            row.get("volume"),
                            row.get("open_net_inflow"),
                        )
                        for row in rows
                    ],
                )
            connection.execute(
                """
                INSERT INTO auction_day_meta (trade_date, fetched_at, source, total_count, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(trade_date) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    source = excluded.source,
                    total_count = excluded.total_count,
                    updated_at = datetime('now')
                """,
                (trade_date, fetched_at, source, len(rows)),
            )
        return len(rows)

    def query_stock_rows(
        self,
        trade_date: str,
        *,
        sort: str = AUCTION_BOARD_DEFAULT_SORT,
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        sort_key = sort if sort in AUCTION_BOARD_SORT_KEYS else AUCTION_BOARD_DEFAULT_SORT
        column = _SORT_COLUMNS[sort_key]
        safe_offset = max(0, int(offset))
        safe_limit = max(1, min(int(limit), 500))
        filters = ["trade_date = ?"]
        params: list[Any] = [trade_date]
        query_text = (q or "").strip()
        if query_text:
            filters.append("(code LIKE ? OR name LIKE ?)")
            like = f"%{query_text}%"
            params.extend([like, like])
        where_sql = " AND ".join(filters)
        order_sql = (
            f"ORDER BY ({column} IS NULL) ASC, {column} DESC, code ASC"
        )
        with self._session() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) FROM auction_stock_row WHERE {where_sql}",
                params,
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            rows = connection.execute(
                f"""
                SELECT symbol, code, name, price, change_pct, volume_ratio, amount, volume, open_net_inflow
                FROM auction_stock_row
                WHERE {where_sql}
                {order_sql}
                LIMIT ? OFFSET ?
                """,
                [*params, safe_limit, safe_offset],
            ).fetchall()
        items = [
            {
                "symbol": str(row[0]),
                "code": str(row[1]),
                "name": str(row[2]),
                "price": row[3],
                "change_pct": row[4],
                "volume_ratio": row[5],
                "amount": row[6],
                "volume": row[7],
                "open_net_inflow": row[8],
            }
            for row in rows
        ]
        return items, total

    @contextmanager
    def _session(self):
        connection = sqlite3.connect(self._db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()
