from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from workbench.domain import Bar, BarPeriod
from workbench.storage.schema import configure_hot_connection

HISTORY_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS schema_version (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bar_cache (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (symbol, period, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_bar_cache_symbol_period
ON bar_cache(symbol, period, timestamp);
"""

CURRENT_SCHEMA_VERSION = 1


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _session(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if readonly and not self.path.is_file():
            raise FileNotFoundError(str(self.path))
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        configure_hot_connection(connection)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._session() as connection:
            connection.executescript(HISTORY_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_version(singleton, version) VALUES(1, ?)",
                (CURRENT_SCHEMA_VERSION,),
            )

    def replace_bars(
        self,
        *,
        symbol: str,
        period: BarPeriod,
        bars: list[Bar],
        source: str,
    ) -> None:
        if not bars:
            return
        with self._session() as connection:
            connection.executemany(
                "INSERT INTO bar_cache("
                "symbol, period, timestamp, open, high, low, close, volume, amount, source"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol, period, timestamp) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, "
                "close=excluded.close, volume=excluded.volume, amount=excluded.amount, "
                "source=excluded.source",
                [
                    (
                        symbol.upper(),
                        period,
                        bar.timestamp.isoformat(sep=" ", timespec="minutes"),
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        bar.amount,
                        source,
                    )
                    for bar in bars
                ],
            )

    def fetch_bars(self, symbol: str, period: BarPeriod, count: int) -> list[Bar]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM bar_cache WHERE symbol=? AND period=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (symbol.upper(), period, count),
            ).fetchall()
        bars = [
            Bar(
                symbol=str(row["symbol"]),
                period=period,
                timestamp=datetime.fromisoformat(str(row["timestamp"])),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                amount=float(row["amount"]),
            )
            for row in reversed(rows)
        ]
        return bars

    def has_bars(self, symbol: str, period: BarPeriod) -> bool:
        with self._session(readonly=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM bar_cache WHERE symbol=? AND period=? LIMIT 1",
                (symbol.upper(), period),
            ).fetchone()
        return row is not None
