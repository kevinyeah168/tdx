from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from datetime import date as date_type

from workbench.collector.trading_clock import (
    clip_minute_for_live_session,
    filter_minutes_for_live_session,
    should_include_closing_minute,
)
from workbench.domain import CollectionStatus, SectorMinute, StockGrayMinute, StockMinute
from workbench.storage.migrations import ensure_hot_schema
from workbench.storage.schema import HOT_SCHEMA, configure_hot_connection


LEGACY_CATALOG_VERSION = "legacy-unknown"
TICK_BACKFILL_BATCH_MARKER = "backfill-tick"
YUNTU_BATCH_MARKER = "yuntu"
_INIT_CACHE_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[str] = set()
_INIT_RETRY_ATTEMPTS = 8
# Flat MAC stock-tick curves (all-zero momentum) are treated as missing.
_FLAT_TICK_ABS_EPS = 1e6  # 100万



@dataclass(frozen=True)
class CompleteFundCurve:
    latest_complete_minute: str | None
    rows: list[dict[str, Any]]


STOCK_UPSERT = """
INSERT INTO stock_minute(
    trade_date, minute, symbol, close, change_pct, amount_delta,
    main_delta, main_cum, super_delta, super_cum, large_delta, large_cum,
    medium_delta, medium_cum, small_delta, small_cum,
    tier_meta_json, observed_at, batch_id
) VALUES(
    :trade_date, :minute, :symbol, :close, :change_pct, :amount_delta,
    :main_delta, :main_cum, :super_delta, :super_cum, :large_delta, :large_cum,
    :medium_delta, :medium_cum, :small_delta, :small_cum,
    :tier_meta_json, :observed_at, :batch_id
) ON CONFLICT(trade_date, minute, symbol) DO UPDATE SET
    close=excluded.close,
    change_pct=excluded.change_pct,
    amount_delta=excluded.amount_delta,
    main_delta=excluded.main_delta,
    main_cum=excluded.main_cum,
    super_delta=excluded.super_delta,
    super_cum=excluded.super_cum,
    large_delta=excluded.large_delta,
    large_cum=excluded.large_cum,
    medium_delta=excluded.medium_delta,
    medium_cum=excluded.medium_cum,
    small_delta=excluded.small_delta,
    small_cum=excluded.small_cum,
    tier_meta_json=excluded.tier_meta_json,
    observed_at=excluded.observed_at,
    batch_id=excluded.batch_id
"""

SECTOR_UPSERT = """
INSERT INTO sector_minute(
    trade_date, minute, sector_id, change_pct, member_count,
    main_delta, main_cum, super_delta, super_cum, large_delta, large_cum,
    medium_delta, medium_cum, small_delta, small_cum,
    tier_meta_json, observed_at, batch_id
) VALUES(
    :trade_date, :minute, :sector_id, :change_pct, :member_count,
    :main_delta, :main_cum, :super_delta, :super_cum, :large_delta, :large_cum,
    :medium_delta, :medium_cum, :small_delta, :small_cum,
    :tier_meta_json, :observed_at, :batch_id
) ON CONFLICT(trade_date, minute, sector_id) DO UPDATE SET
    change_pct=excluded.change_pct,
    member_count=excluded.member_count,
    main_delta=excluded.main_delta,
    main_cum=excluded.main_cum,
    super_delta=excluded.super_delta,
    super_cum=excluded.super_cum,
    large_delta=excluded.large_delta,
    large_cum=excluded.large_cum,
    medium_delta=excluded.medium_delta,
    medium_cum=excluded.medium_cum,
    small_delta=excluded.small_delta,
    small_cum=excluded.small_cum,
    tier_meta_json=excluded.tier_meta_json,
    observed_at=excluded.observed_at,
    batch_id=excluded.batch_id
"""

STOCK_GRAY_UPSERT = """
INSERT INTO stock_gray_minute(
    trade_date, minute, symbol, code, open_cum, dark_cum, total_cum,
    observed_at, batch_id, source
) VALUES(
    :trade_date, :minute, :symbol, :code, :open_cum, :dark_cum, :total_cum,
    :observed_at, :batch_id, :source
) ON CONFLICT(trade_date, minute, symbol) DO UPDATE SET
    code=excluded.code,
    open_cum=excluded.open_cum,
    dark_cum=excluded.dark_cum,
    total_cum=excluded.total_cum,
    observed_at=excluded.observed_at,
    batch_id=excluded.batch_id,
    source=excluded.source
"""

STATUS_UPSERT = """
INSERT INTO collection_status(
    trade_date, minute, batch_id, catalog_version,
    expected_stocks, collected_stocks, expected_sectors, collected_sectors,
    duration_ms, coverage_pct, status, error_summary
) VALUES(
    :trade_date, :minute, :batch_id, :catalog_version,
    :expected_stocks, :collected_stocks, :expected_sectors, :collected_sectors,
    :duration_ms, :coverage_pct, :status, :error_summary
) ON CONFLICT(trade_date, minute) DO UPDATE SET
    batch_id=excluded.batch_id,
    catalog_version=excluded.catalog_version,
    expected_stocks=excluded.expected_stocks,
    collected_stocks=excluded.collected_stocks,
    expected_sectors=excluded.expected_sectors,
    collected_sectors=excluded.collected_sectors,
    duration_ms=excluded.duration_ms,
    coverage_pct=excluded.coverage_pct,
    status=excluded.status,
    error_summary=excluded.error_summary
"""


def _tier_meta(record: StockMinute | SectorMinute) -> str:
    return json.dumps(
        {
            name: {"source": point.source, "quality": point.quality.value}
            for name, point in {
                "main": record.funds.main,
                "super": record.funds.super,
                "large": record.funds.large,
                "medium": record.funds.medium,
                "small": record.funds.small,
            }.items()
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _stock_params(record: StockMinute) -> dict[str, Any]:
    return {
        "trade_date": record.trade_date.isoformat(),
        "minute": record.minute,
        "symbol": record.symbol,
        "close": record.close,
        "change_pct": record.change_pct,
        "amount_delta": record.amount_delta,
        "main_delta": record.funds.main.delta,
        "main_cum": record.funds.main.cumulative,
        "super_delta": record.funds.super.delta,
        "super_cum": record.funds.super.cumulative,
        "large_delta": record.funds.large.delta,
        "large_cum": record.funds.large.cumulative,
        "medium_delta": record.funds.medium.delta,
        "medium_cum": record.funds.medium.cumulative,
        "small_delta": record.funds.small.delta,
        "small_cum": record.funds.small.cumulative,
        "tier_meta_json": _tier_meta(record),
        "observed_at": record.observed_at.isoformat(),
        "batch_id": record.batch_id,
    }


def _sector_params(record: SectorMinute) -> dict[str, Any]:
    return {
        "trade_date": record.trade_date.isoformat(),
        "minute": record.minute,
        "sector_id": record.sector_id,
        "change_pct": record.change_pct,
        "member_count": record.member_count,
        "main_delta": record.funds.main.delta,
        "main_cum": record.funds.main.cumulative,
        "super_delta": record.funds.super.delta,
        "super_cum": record.funds.super.cumulative,
        "large_delta": record.funds.large.delta,
        "large_cum": record.funds.large.cumulative,
        "medium_delta": record.funds.medium.delta,
        "medium_cum": record.funds.medium.cumulative,
        "small_delta": record.funds.small.delta,
        "small_cum": record.funds.small.cumulative,
        "tier_meta_json": _tier_meta(record),
        "observed_at": record.observed_at.isoformat(),
        "batch_id": record.batch_id,
    }


def _stock_gray_params(record: StockGrayMinute) -> dict[str, Any]:
    return {
        "trade_date": record.trade_date.isoformat(),
        "minute": record.minute,
        "symbol": record.symbol.upper(),
        "code": record.code,
        "open_cum": record.open_cum,
        "dark_cum": record.dark_cum,
        "total_cum": record.total_cum,
        "observed_at": record.observed_at.isoformat(),
        "batch_id": record.batch_id,
        "source": record.source,
    }


class HotStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            # mode=ro forbids writes while retaining SQLite's WAL sidecars as concurrency metadata.
            connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path)
        configure_hot_connection(connection)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect(readonly=readonly)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        key = str(self.path.resolve())
        with _INIT_CACHE_LOCK:
            if key in _INITIALIZED_PATHS:
                return

        last_error: sqlite3.OperationalError | None = None
        for attempt in range(_INIT_RETRY_ATTEMPTS):
            try:
                self._initialize_once()
            except sqlite3.OperationalError as error:
                message = str(error).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                last_error = error
                time.sleep(min(0.1 * (2**attempt), 2.0))
                continue
            with _INIT_CACHE_LOCK:
                _INITIALIZED_PATHS.add(key)
            return
        if last_error is not None:
            raise last_error

    def _initialize_once(self) -> None:
        with self._session() as connection:
            connection.executescript(HOT_SCHEMA)
            ensure_hot_schema(connection)
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(collection_status)")
            }
            if "catalog_version" in columns:
                return
            connection.execute("BEGIN IMMEDIATE")
            try:
                columns = {
                    str(row[1]) for row in connection.execute("PRAGMA table_info(collection_status)")
                }
                if "catalog_version" not in columns:
                    connection.execute(
                        "ALTER TABLE collection_status "
                        f"ADD COLUMN catalog_version TEXT NOT NULL DEFAULT '{LEGACY_CATALOG_VERSION}'"
                    )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def write_stocks(self, records: list[StockMinute]) -> None:
        with self._session() as connection:
            connection.executemany(STOCK_UPSERT, [_stock_params(record) for record in records])

    def write_stock_gray(self, records: list[StockGrayMinute]) -> None:
        if not records:
            return
        with self._session() as connection:
            connection.executemany(STOCK_GRAY_UPSERT, [_stock_gray_params(record) for record in records])

    def write_sectors(self, records: list[SectorMinute]) -> None:
        if not records:
            return
        with self._session() as connection:
            connection.executemany(SECTOR_UPSERT, [_sector_params(record) for record in records])

    def delete_sector_day(self, trade_date: str, sector_id: str) -> int:
        with self._session() as connection:
            deleted = connection.execute(
                "DELETE FROM sector_minute WHERE trade_date=? AND sector_id=?",
                (trade_date, sector_id),
            ).rowcount
        return int(deleted or 0)

    def delete_sector_tick_backfill(self, trade_date: str, sector_id: str) -> int:
        pattern = f"%{TICK_BACKFILL_BATCH_MARKER}%"
        with self._session() as connection:
            deleted = connection.execute(
                """
                DELETE FROM sector_minute
                WHERE trade_date=? AND sector_id=? AND batch_id LIKE ?
                """,
                (trade_date, sector_id, pattern),
            ).rowcount
        return int(deleted or 0)

    def delete_stock_day(self, trade_date: str, symbol: str) -> int:
        with self._session() as connection:
            deleted = connection.execute(
                "DELETE FROM stock_minute WHERE trade_date=? AND symbol=?",
                (trade_date, symbol.upper()),
            ).rowcount
        return int(deleted or 0)

    def delete_sector_minutes(self, trade_date: str, sector_id: str, minutes: tuple[str, ...]) -> None:
        if not minutes:
            return
        placeholders = ",".join("?" * len(minutes))
        with self._session() as connection:
            connection.execute(
                f"DELETE FROM sector_minute WHERE trade_date=? AND sector_id=? AND minute IN ({placeholders})",
                (trade_date, sector_id, *minutes),
            )

    def delete_stock_minutes(self, trade_date: str, symbol: str, minutes: tuple[str, ...]) -> None:
        if not minutes:
            return
        placeholders = ",".join("?" * len(minutes))
        with self._session() as connection:
            connection.execute(
                f"DELETE FROM stock_minute WHERE trade_date=? AND symbol=? AND minute IN ({placeholders})",
                (trade_date, symbol.upper(), *minutes),
            )

    def upsert_priority_minute_status(
        self,
        *,
        trade_date: str,
        minute: str,
        batch_id: str,
        catalog_version: str,
        collected_sectors: int,
        collected_stocks: int,
        expected_sectors: int,
        expected_stocks: int,
        duration_ms: int,
    ) -> None:
        if collected_sectors <= 0 and collected_stocks <= 0:
            return
        from datetime import date as date_type

        from workbench.domain import CollectionStatus

        safe_expected_stocks = max(expected_stocks, collected_stocks, 1)
        safe_expected_sectors = max(expected_sectors, collected_sectors, 1)
        coverage_pct = round(collected_stocks / safe_expected_stocks * 100.0, 4)
        is_complete = coverage_pct >= 99.5 and collected_sectors == safe_expected_sectors
        status = CollectionStatus(
            trade_date=date_type.fromisoformat(trade_date),
            minute=minute,
            batch_id=batch_id,
            catalog_version=catalog_version or "unknown",
            expected_stocks=safe_expected_stocks,
            collected_stocks=collected_stocks,
            expected_sectors=safe_expected_sectors,
            collected_sectors=collected_sectors,
            duration_ms=max(duration_ms, 0),
            coverage_pct=coverage_pct,
            status="complete" if is_complete else "partial",
            error_summary="" if is_complete else "priority-batch",
        )
        with self._session() as connection:
            connection.execute(STATUS_UPSERT, status.model_dump(mode="json"))

    def count_sector_minutes(self, trade_date: str, sector_id: str) -> int:
        with self._session(readonly=True) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM sector_minute WHERE trade_date=? AND sector_id=?",
                (trade_date, sector_id),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_stock_minutes(self, trade_date: str, symbol: str) -> int:
        with self._session(readonly=True) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM stock_minute WHERE trade_date=? AND symbol=?",
                (trade_date, symbol.upper()),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_sector_tick_backfill_minutes(self, trade_date: str, sector_id: str) -> int:
        pattern = f"%{TICK_BACKFILL_BATCH_MARKER}%"
        with self._session(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM sector_minute
                WHERE trade_date=? AND sector_id=? AND batch_id LIKE ?
                """,
                (trade_date, sector_id, pattern),
            ).fetchone()
        return int(row[0]) if row else 0

    def latest_sector_tick_backfill_minute(self, trade_date: str, sector_id: str) -> str | None:
        pattern = f"%{TICK_BACKFILL_BATCH_MARKER}%"
        with self._session(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT MAX(minute) FROM sector_minute
                WHERE trade_date=? AND sector_id=? AND batch_id LIKE ?
                """,
                (trade_date, sector_id, pattern),
            ).fetchone()
        minute = str(row[0]) if row and row[0] else None
        return clip_minute_for_live_session(date_type.fromisoformat(trade_date), minute)

    def count_stock_tick_backfill_minutes(self, trade_date: str, symbol: str) -> int:
        pattern = f"%{TICK_BACKFILL_BATCH_MARKER}%"
        with self._session(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM stock_minute
                WHERE trade_date=? AND symbol=? AND batch_id LIKE ?
                  AND ABS(main_cum) >= ?
                """,
                (trade_date, symbol.upper(), pattern, _FLAT_TICK_ABS_EPS),
            ).fetchone()
        return int(row[0]) if row else 0

    def delete_flat_stock_tick_backfill(self, trade_date: str) -> int:
        """Remove useless all-zero stock tick curves that create chart cliffs."""
        pattern = f"%{TICK_BACKFILL_BATCH_MARKER}%"
        with self._session() as connection:
            deleted = connection.execute(
                """
                DELETE FROM stock_minute
                WHERE trade_date=? AND batch_id LIKE ?
                  AND symbol IN (
                    SELECT symbol FROM stock_minute
                    WHERE trade_date=? AND batch_id LIKE ?
                    GROUP BY symbol
                    HAVING MAX(ABS(main_cum)) < ?
                  )
                """,
                (trade_date, pattern, trade_date, pattern, _FLAT_TICK_ABS_EPS),
            ).rowcount
        return int(deleted or 0)

    def write_complete_batch(
        self,
        stocks: list[StockMinute],
        sectors: list[SectorMinute],
        status: CollectionStatus,
        *,
        started_at: float,
    ) -> dict[str, int | float | str]:
        validated_status = CollectionStatus.model_validate(status.model_dump())
        self._validate_batch_identity(stocks, sectors, validated_status)
        with self._session() as connection:
            connection.execute(
                "DELETE FROM stock_minute WHERE trade_date=? AND minute=?",
                (validated_status.trade_date.isoformat(), validated_status.minute),
            )
            connection.execute(
                "DELETE FROM sector_minute WHERE trade_date=? AND minute=?",
                (validated_status.trade_date.isoformat(), validated_status.minute),
            )
            connection.executemany(STOCK_UPSERT, [_stock_params(record) for record in stocks])
            connection.executemany(SECTOR_UPSERT, [_sector_params(record) for record in sectors])
            # Includes transaction writes through sector persistence, excluding status/commit latency.
            final_status = validated_status.model_copy(
                update={"duration_ms": int((time.perf_counter() - started_at) * 1000)}
            )
            connection.execute(STATUS_UPSERT, final_status.model_dump(mode="json"))
        return final_status.model_dump(mode="json")

    @staticmethod
    def _validate_batch_identity(
        stocks: list[StockMinute], sectors: list[SectorMinute], status: CollectionStatus
    ) -> None:
        if len({record.symbol for record in stocks}) != len(stocks):
            raise ValueError("duplicate stock symbols")
        if len({record.sector_id for record in sectors}) != len(sectors):
            raise ValueError("duplicate sector IDs")
        if status.collected_stocks != len(stocks):
            raise ValueError("collected_stocks must match stock records")
        if status.collected_sectors != len(sectors):
            raise ValueError("collected_sectors must match sector records")
        expected_identity = (status.trade_date, status.minute, status.batch_id)
        for record in [*stocks, *sectors]:
            if (record.trade_date, record.minute, record.batch_id) != expected_identity:
                raise ValueError("records must match status trade_date, minute, and batch_id")

    def _filter_live_rows(self, trade_date: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return rows
        allowed = set(
            filter_minutes_for_live_session(
                date_type.fromisoformat(trade_date),
                sorted({str(row["minute"]) for row in rows}),
            )
        )
        return [row for row in rows if str(row["minute"]) in allowed]

    def purge_intraday_closing_minutes(self, trade_date: str) -> int:
        """Remove synthetic 15:00 tick-backfill rows while the session is still open."""
        if should_include_closing_minute(date_type.fromisoformat(trade_date)):
            return 0
        with self._session() as connection:
            sector_deleted = connection.execute(
                "DELETE FROM sector_minute WHERE trade_date=? AND minute='15:00'",
                (trade_date,),
            ).rowcount
            stock_deleted = connection.execute(
                "DELETE FROM stock_minute WHERE trade_date=? AND minute='15:00'",
                (trade_date,),
            ).rowcount
        return int(sector_deleted or 0) + int(stock_deleted or 0)

    def stock_fund_series(self, trade_date: str, symbol: str) -> list[dict[str, Any]]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM stock_minute WHERE trade_date=? AND symbol=? ORDER BY minute",
                (trade_date, symbol),
            ).fetchall()
        parsed = [dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows]
        return self._filter_live_rows(
            trade_date,
            self._published_snapshot_rows(trade_date, parsed),
        )

    def sector_fund_series(self, trade_date: str, sector_id: str) -> list[dict[str, Any]]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM sector_minute WHERE trade_date=? AND sector_id=? ORDER BY minute",
                (trade_date, sector_id),
            ).fetchall()
        parsed = [dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows]
        return self._filter_live_rows(
            trade_date,
            self._published_snapshot_rows(trade_date, parsed),
        )

    def sector_fund_tip(
        self,
        trade_date: str,
        sector_id: str,
        minute: str | None = None,
    ) -> dict[str, Any] | None:
        series = self.sector_fund_series(trade_date, sector_id)
        if not series:
            return None
        if minute:
            for row in reversed(series):
                if str(row["minute"]) <= minute:
                    return row
        return series[-1]

    def complete_stock_fund_series(self, trade_date: str, symbol: str) -> list[dict[str, Any]]:
        return self.complete_stock_fund_curve(trade_date, symbol).rows

    def complete_sector_fund_series(self, trade_date: str, sector_id: str) -> list[dict[str, Any]]:
        return self.complete_sector_fund_curve(trade_date, sector_id).rows

    def complete_stock_fund_curve(self, trade_date: str, symbol: str) -> CompleteFundCurve:
        return self._complete_fund_curve("stock_minute", "symbol", trade_date, symbol)

    def complete_sector_fund_curve(self, trade_date: str, sector_id: str) -> CompleteFundCurve:
        rows = self.sector_fund_series(trade_date, sector_id)
        latest = self.latest_available_minute(trade_date)
        if latest is None and rows:
            latest = str(rows[-1]["minute"])
        latest = clip_minute_for_live_session(
            date_type.fromisoformat(trade_date),
            latest,
        )
        return CompleteFundCurve(
            latest_complete_minute=latest,
            rows=rows,
        )

    def live_stock_fund_curve(self, trade_date: str, symbol: str) -> CompleteFundCurve:
        with self._session(readonly=True) as connection:
            latest_row = connection.execute(
                "SELECT MAX(minute) FROM collection_status WHERE trade_date=? AND status='complete'",
                (trade_date,),
            ).fetchone()
            rows = connection.execute(
                "SELECT * FROM stock_minute WHERE trade_date=? AND symbol=? ORDER BY minute",
                (trade_date, symbol.upper()),
            ).fetchall()
        parsed = [dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows]
        latest = str(latest_row[0]) if latest_row and latest_row[0] else None
        ordered = self._filter_live_rows(
            trade_date,
            self._published_snapshot_rows(trade_date, parsed),
        )
        latest = clip_minute_for_live_session(
            date_type.fromisoformat(trade_date),
            latest,
        )
        if latest is not None:
            ordered = [row for row in ordered if str(row["minute"]) <= latest]
        elif ordered:
            latest = str(ordered[-1]["minute"])
        return CompleteFundCurve(latest_complete_minute=latest, rows=ordered)

    def stock_gray_curve(self, trade_date: str, symbol: str) -> CompleteFundCurve:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM stock_gray_minute WHERE trade_date=? AND symbol=? ORDER BY minute",
                (trade_date, symbol.upper()),
            ).fetchall()
        ordered = [dict(row) for row in rows]
        ordered = self._filter_live_rows(trade_date, ordered)
        latest = ordered[-1]["minute"] if ordered else None
        latest = clip_minute_for_live_session(
            date_type.fromisoformat(trade_date),
            str(latest) if latest else None,
        )
        return CompleteFundCurve(latest_complete_minute=latest, rows=ordered)

    @staticmethod
    def _is_tick_backfill_batch(batch_id: object) -> bool:
        return TICK_BACKFILL_BATCH_MARKER in str(batch_id or "")

    @staticmethod
    def _is_yuntu_batch(batch_id: object) -> bool:
        batch = str(batch_id or "")
        return YUNTU_BATCH_MARKER in batch

    @classmethod
    def _snapshot_fund_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return minute snapshots from yuntu/official rows; drop legacy MAC tick backfill."""
        if not rows:
            return rows
        filtered = [
            row for row in rows if not cls._is_tick_backfill_batch(row.get("batch_id"))
        ]
        by_minute: dict[str, dict[str, Any]] = {}
        for row in sorted(filtered, key=lambda item: str(item["minute"])):
            minute = str(row["minute"])
            batch_id = str(row.get("batch_id") or "")
            existing = by_minute.get(minute)
            if existing is None:
                by_minute[minute] = row
                continue
            if cls._is_yuntu_batch(batch_id) and not cls._is_yuntu_batch(existing.get("batch_id")):
                by_minute[minute] = row
        return [by_minute[minute] for minute in sorted(by_minute)]

    def _complete_status_batches(self, trade_date: str) -> dict[str, str]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT minute, batch_id FROM collection_status "
                "WHERE trade_date=? AND status='complete'",
                (trade_date,),
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def _published_snapshot_rows(
        self, trade_date: str, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        snapshots = self._snapshot_fund_rows(rows)
        if any(self._is_yuntu_batch(row.get("batch_id")) for row in snapshots):
            return snapshots
        status_batches = self._complete_status_batches(trade_date)
        if status_batches:
            return [
                row
                for row in snapshots
                if str(row["minute"]) in status_batches
                and str(row.get("batch_id")) == status_batches[str(row["minute"])]
            ]
        return snapshots

    @classmethod
    def _prefer_sector_fund_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return cls._snapshot_fund_rows(rows)

    @classmethod
    def _prefer_tick_fund_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return cls._snapshot_fund_rows(rows)

    def latest_stock_minute(self, trade_date: str) -> str | None:
        with self._session(readonly=True) as connection:
            row = connection.execute(
                "SELECT MAX(minute) FROM stock_minute WHERE trade_date=?",
                (trade_date,),
            ).fetchone()
        minute = str(row[0]) if row and row[0] else None
        return clip_minute_for_live_session(date_type.fromisoformat(trade_date), minute)

    def session_minutes(self, trade_date: str) -> list[str]:
        complete = set(self._complete_minutes(trade_date))
        with self._session(readonly=True) as connection:
            sector_rows = connection.execute(
                "SELECT DISTINCT minute FROM sector_minute WHERE trade_date=? ORDER BY minute",
                (trade_date,),
            ).fetchall()
            stock_rows = connection.execute(
                "SELECT DISTINCT minute FROM stock_minute WHERE trade_date=? ORDER BY minute",
                (trade_date,),
            ).fetchall()
        for row in sector_rows:
            complete.add(str(row[0]))
        for row in stock_rows:
            complete.add(str(row[0]))
        return filter_minutes_for_live_session(
            date_type.fromisoformat(trade_date),
            sorted(complete),
        )

    def _complete_minutes(self, trade_date: str) -> list[str]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT minute FROM collection_status WHERE trade_date=? AND status='complete' ORDER BY minute",
                (trade_date,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def latest_available_minute(self, trade_date: str) -> str | None:
        candidates = [
            self.latest_complete_minute(trade_date),
            self.latest_sector_minute(trade_date),
            self.latest_stock_minute(trade_date),
        ]
        present = [minute for minute in candidates if minute]
        minute = max(present) if present else None
        return clip_minute_for_live_session(date_type.fromisoformat(trade_date), minute)

    def _complete_fund_curve(
        self, table: str, entity_column: str, trade_date: str, entity_id: str
    ) -> CompleteFundCurve:
        with self._session(readonly=True) as connection:
            connection.execute("BEGIN")
            cursor = connection.execute(
                "SELECT MAX(minute) FROM collection_status WHERE trade_date=? AND status='complete'",
                (trade_date,),
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT series.*
                FROM {table} AS series
                INNER JOIN collection_status AS status
                    ON status.trade_date = series.trade_date
                    AND status.minute = series.minute
                    AND status.batch_id = series.batch_id
                    AND status.status = 'complete'
                WHERE series.trade_date=? AND series.{entity_column}=?
                ORDER BY series.minute
                """,
                (trade_date, entity_id),
            ).fetchall()
        return CompleteFundCurve(
            latest_complete_minute=str(cursor[0]) if cursor and cursor[0] else None,
            rows=[dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows],
        )

    def latest_complete_minute(self, trade_date: str) -> str | None:
        with self._session(readonly=True) as connection:
            row = connection.execute(
                "SELECT MAX(minute) FROM collection_status WHERE trade_date=? AND status='complete'",
                (trade_date,),
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def latest_sector_minute(self, trade_date: str) -> str | None:
        with self._session(readonly=True) as connection:
            row = connection.execute(
                "SELECT MAX(minute) FROM sector_minute WHERE trade_date=?",
                (trade_date,),
            ).fetchone()
        minute = str(row[0]) if row and row[0] else None
        return clip_minute_for_live_session(date_type.fromisoformat(trade_date), minute)

    def record_gap(
        self,
        *,
        entity_type: str,
        entity_id: str,
        trade_date: str,
        minute: str,
        reason: str,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                "INSERT INTO data_gap("
                "entity_type, entity_id, trade_date, minute, reason, retry_count, resolved"
                ") VALUES(?, ?, ?, ?, ?, 0, 0) "
                "ON CONFLICT(entity_type, entity_id, trade_date, minute) DO UPDATE SET "
                "reason=excluded.reason, retry_count=data_gap.retry_count + 1",
                (entity_type, entity_id, trade_date, minute, reason),
            )

    def unresolved_gaps(self, trade_date: str) -> list[dict[str, str | int]]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT entity_type, entity_id, trade_date, minute, reason, retry_count "
                "FROM data_gap WHERE trade_date=? AND resolved=0 ORDER BY minute, entity_id",
                (trade_date,),
            ).fetchall()
        return [
            {
                "entity_type": str(row[0]),
                "entity_id": str(row[1]),
                "trade_date": str(row[2]),
                "minute": str(row[3]),
                "reason": str(row[4]),
                "retry_count": int(row[5]),
            }
            for row in rows
        ]

    def resolve_gap(
        self,
        *,
        entity_type: str,
        entity_id: str,
        trade_date: str,
        minute: str,
    ) -> None:
        with self._session() as connection:
            connection.execute(
                "UPDATE data_gap SET resolved=1 "
                "WHERE entity_type=? AND entity_id=? AND trade_date=? AND minute=?",
                (entity_type, entity_id, trade_date, minute),
            )
