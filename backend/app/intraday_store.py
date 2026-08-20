from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")


def snapshots_to_flow(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert stored minute snapshots into cumulative flow rows for charts."""
    flow: list[dict[str, Any]] = []
    prev = 0.0
    for row in rows:
        cum = float(row.get("main_net") or 0)
        point: dict[str, Any] = {
            "time": row["minute"],
            "main_net": round(cum - prev, 2),
            "cum_main": round(cum, 2),
            "cum_net": round(cum, 2),
            "net": round(cum - prev, 2),
        }
        if row.get("price") is not None:
            point["price"] = float(row["price"])
        if row.get("change_pct") is not None:
            point["change_pct"] = float(row["change_pct"])
        flow.append(point)
        prev = cum
    return flow


class IntradayStore:
    """Persist MAC official main-net samples for intraday stock/sector curves."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stock_intraday_snapshots (
                        trade_date TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        minute TEXT NOT NULL,
                        main_net REAL NOT NULL,
                        price REAL,
                        change_pct REAL,
                        sampled_at TEXT NOT NULL,
                        PRIMARY KEY (trade_date, symbol, minute)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_intraday_symbol_date
                    ON stock_intraday_snapshots(symbol, trade_date)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sector_intraday_snapshots (
                        trade_date TEXT NOT NULL,
                        sector_id TEXT NOT NULL,
                        minute TEXT NOT NULL,
                        main_net REAL NOT NULL,
                        price REAL,
                        change_pct REAL,
                        sampled_at TEXT NOT NULL,
                        PRIMARY KEY (trade_date, sector_id, minute)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_sector_intraday_date
                    ON sector_intraday_snapshots(sector_id, trade_date)
                    """
                )
                conn.commit()

    def append_stock_snapshot(
        self,
        trade_date: str,
        symbol: str,
        minute: str,
        main_net: float,
        *,
        price: float | None = None,
        change_pct: float | None = None,
    ) -> None:
        sym = symbol.upper().replace(".", "")
        sampled_at = datetime.now(CHINA).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO stock_intraday_snapshots (
                        trade_date, symbol, minute, main_net, price, change_pct, sampled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, symbol, minute) DO UPDATE SET
                        main_net = excluded.main_net,
                        price = excluded.price,
                        change_pct = excluded.change_pct,
                        sampled_at = excluded.sampled_at
                    """,
                    (trade_date, sym, minute, float(main_net), price, change_pct, sampled_at),
                )
                conn.commit()

    def append_sector_snapshot(
        self,
        trade_date: str,
        sector_id: str,
        minute: str,
        main_net: float,
        *,
        price: float | None = None,
        change_pct: float | None = None,
    ) -> None:
        sid = str(sector_id).strip()
        sampled_at = datetime.now(CHINA).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sector_intraday_snapshots (
                        trade_date, sector_id, minute, main_net, price, change_pct, sampled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, sector_id, minute) DO UPDATE SET
                        main_net = excluded.main_net,
                        price = excluded.price,
                        change_pct = excluded.change_pct,
                        sampled_at = excluded.sampled_at
                    """,
                    (trade_date, sid, minute, float(main_net), price, change_pct, sampled_at),
                )
                conn.commit()

    def append_snapshot(
        self,
        trade_date: str,
        symbol: str,
        minute: str,
        main_net: float,
        *,
        price: float | None = None,
        change_pct: float | None = None,
    ) -> None:
        self.append_stock_snapshot(trade_date, symbol, minute, main_net, price=price, change_pct=change_pct)

    def replace_sector_flow(self, trade_date: str, sector_id: str, flow: list[dict[str, Any]]) -> None:
        """Replace all minute snapshots for a sector/day (used after market close)."""
        if not flow:
            return
        sid = str(sector_id).strip()
        sampled_at = datetime.now(CHINA).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM sector_intraday_snapshots WHERE trade_date = ? AND sector_id = ?",
                    (trade_date, sid),
                )
                for point in flow:
                    minute = str(point.get("time") or "").strip()
                    if not minute:
                        continue
                    conn.execute(
                        """
                        INSERT INTO sector_intraday_snapshots (
                            trade_date, sector_id, minute, main_net, price, change_pct, sampled_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trade_date,
                            sid,
                            minute,
                            float(point.get("cum_main") or point.get("cum_net") or 0),
                            point.get("price"),
                            point.get("change_pct"),
                            sampled_at,
                        ),
                    )
                conn.commit()

    def replace_stock_flow(self, trade_date: str, symbol: str, flow: list[dict[str, Any]]) -> None:
        """Replace all minute snapshots for a stock/day (used after market close)."""
        if not flow:
            return
        sym = symbol.upper().replace(".", "")
        sampled_at = datetime.now(CHINA).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM stock_intraday_snapshots WHERE trade_date = ? AND symbol = ?",
                    (trade_date, sym),
                )
                for point in flow:
                    minute = str(point.get("time") or "").strip()
                    if not minute:
                        continue
                    conn.execute(
                        """
                        INSERT INTO stock_intraday_snapshots (
                            trade_date, symbol, minute, main_net, price, change_pct, sampled_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            trade_date,
                            sym,
                            minute,
                            float(point.get("cum_main") or point.get("cum_net") or 0),
                            point.get("price"),
                            point.get("change_pct"),
                            sampled_at,
                        ),
                    )
                conn.commit()

    def load_stock_series(self, trade_date: str, symbol: str) -> list[dict[str, Any]]:
        sym = symbol.upper().replace(".", "")
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT minute, main_net, price, change_pct, sampled_at
                    FROM stock_intraday_snapshots
                    WHERE trade_date = ? AND symbol = ?
                    ORDER BY minute
                    """,
                    (trade_date, sym),
                ).fetchall()
        return [dict(row) for row in rows]

    def load_series(self, trade_date: str, symbol: str) -> list[dict[str, Any]]:
        return self.load_stock_series(trade_date, symbol)

    def load_sector_series(self, trade_date: str, sector_id: str) -> list[dict[str, Any]]:
        sid = str(sector_id).strip()
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT minute, main_net, price, change_pct, sampled_at
                    FROM sector_intraday_snapshots
                    WHERE trade_date = ? AND sector_id = ?
                    ORDER BY minute
                    """,
                    (trade_date, sid),
                ).fetchall()
        return [dict(row) for row in rows]

    def is_bulk_archived_sector_series(self, trade_date: str, sector_id: str) -> bool:
        """Detect momentum close-archive rows (many minutes, identical sampled_at)."""
        rows = self.load_sector_series(trade_date, sector_id)
        if len(rows) < 50:
            return False
        sampled_times = {str(r.get("sampled_at") or "") for r in rows}
        return len(sampled_times) == 1

    def delete_sector_series(self, trade_date: str, sector_id: str) -> None:
        sid = str(sector_id).strip()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM sector_intraday_snapshots WHERE trade_date = ? AND sector_id = ?",
                    (trade_date, sid),
                )
                conn.commit()

    def load_series_for_symbols(self, trade_date: str, symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for sym in symbols:
            rows = self.load_stock_series(trade_date, sym)
            if rows:
                out[sym.upper().replace(".", "")] = snapshots_to_flow(rows)
        return out

    def load_series_for_sectors(self, trade_date: str, sector_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for sid in sector_ids:
            rows = self.load_sector_series(trade_date, sid)
            if rows:
                out[str(sid).strip()] = snapshots_to_flow(rows)
        return out

    def list_stock_dates(self, symbols: list[str] | None = None, limit: int = 30) -> list[str]:
        with self._lock:
            with self._connect() as conn:
                if symbols:
                    syms = [s.upper().replace(".", "") for s in symbols]
                    placeholders = ",".join("?" for _ in syms)
                    rows = conn.execute(
                        f"""
                        SELECT DISTINCT trade_date
                        FROM stock_intraday_snapshots
                        WHERE symbol IN ({placeholders})
                        ORDER BY trade_date DESC
                        LIMIT ?
                        """,
                        (*syms, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT trade_date
                        FROM stock_intraday_snapshots
                        ORDER BY trade_date DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
        return [str(row["trade_date"]) for row in rows]

    def list_sector_dates(self, sector_ids: list[str] | None = None, limit: int = 30) -> list[str]:
        with self._lock:
            with self._connect() as conn:
                if sector_ids:
                    ids = [str(s).strip() for s in sector_ids]
                    placeholders = ",".join("?" for _ in ids)
                    rows = conn.execute(
                        f"""
                        SELECT DISTINCT trade_date
                        FROM sector_intraday_snapshots
                        WHERE sector_id IN ({placeholders})
                        ORDER BY trade_date DESC
                        LIMIT ?
                        """,
                        (*ids, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT trade_date
                        FROM sector_intraday_snapshots
                        ORDER BY trade_date DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
        return [str(row["trade_date"]) for row in rows]

    def list_dates(self, symbols: list[str] | None = None, limit: int = 30) -> list[str]:
        return self.list_stock_dates(symbols=symbols, limit=limit)

    def get_latest_stock_date(self, symbols: list[str] | None = None) -> str | None:
        dates = self.list_stock_dates(symbols=symbols, limit=1)
        return dates[0] if dates else None

    def get_latest_sector_date(self, sector_ids: list[str] | None = None) -> str | None:
        dates = self.list_sector_dates(sector_ids=sector_ids, limit=1)
        return dates[0] if dates else None

    def get_latest_date(self, symbols: list[str] | None = None) -> str | None:
        return self.get_latest_stock_date(symbols=symbols)

    def prune_old_dates(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        deleted = 0
        with self._lock:
            with self._connect() as conn:
                for table in ("stock_intraday_snapshots", "sector_intraday_snapshots"):
                    rows = conn.execute(
                        f"SELECT DISTINCT trade_date FROM {table} ORDER BY trade_date DESC"
                    ).fetchall()
                    keep = {str(row["trade_date"]) for row in rows[:retention_days]}
                    if not rows or len(rows) <= retention_days:
                        continue
                    old_dates = [str(row["trade_date"]) for row in rows if str(row["trade_date"]) not in keep]
                    for d in old_dates:
                        cur = conn.execute(f"DELETE FROM {table} WHERE trade_date = ?", (d,))
                        deleted += cur.rowcount
                conn.commit()
        return deleted
