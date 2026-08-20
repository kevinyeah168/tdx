from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from workbench.domain import CollectionStatus, SectorMinute, StockMinute
from workbench.storage.schema import HOT_SCHEMA, configure_hot_connection


LEGACY_CATALOG_VERSION = "legacy-unknown"


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


class HotStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
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
        with self._session() as connection:
            connection.executescript(HOT_SCHEMA)
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(collection_status)")
            }
            if "catalog_version" not in columns:
                connection.execute("BEGIN IMMEDIATE")
                try:
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

    def stock_fund_series(self, trade_date: str, symbol: str) -> list[dict[str, Any]]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM stock_minute WHERE trade_date=? AND symbol=? ORDER BY minute",
                (trade_date, symbol),
            ).fetchall()
        return [dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows]

    def sector_fund_series(self, trade_date: str, sector_id: str) -> list[dict[str, Any]]:
        with self._session(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM sector_minute WHERE trade_date=? AND sector_id=? ORDER BY minute",
                (trade_date, sector_id),
            ).fetchall()
        return [dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows]

    def latest_complete_minute(self, trade_date: str) -> str | None:
        with self._session(readonly=True) as connection:
            row = connection.execute(
                "SELECT MAX(minute) FROM collection_status WHERE trade_date=? AND status='complete'",
                (trade_date,),
            ).fetchone()
        return str(row[0]) if row and row[0] else None
