"""Poll TDX yuntu real_hq every ~15s; upsert one snapshot row per trading minute."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime

from workbench.config import WorkbenchSettings
from workbench.providers.tdx.market_scope_records import (
    build_gap_market_scope_minutes,
    build_market_scope_minutes_from_yuntu,
)
from workbench.providers.tdx.yuntu_minute_records import (
    GAP_BATCH_MARKER,
    YUNTU_SOURCE,
    apply_written_main_cum,
    build_gap_sector_minutes,
    build_gap_stock_minutes,
    build_sector_minutes_from_yuntu,
    build_stock_minutes_from_yuntu,
)
from workbench.providers.tdx.yuntu_sector_flow import decode_real_hq_script, fetch_real_hq_script
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


@dataclass
class YuntuSnapshotCollector:
    meta: MetaStore
    hot: HotStore
    settings: WorkbenchSettings
    _open_minute: str | None = field(default=None, init=False)
    _minutes_with_success: set[str] = field(default_factory=set, init=False)
    _previous_stock_main_cum: dict[str, float] = field(default_factory=dict, init=False)
    _previous_sector_main_cum: dict[str, float] = field(default_factory=dict, init=False)
    _previous_market_scope_main_cum: dict[str, float] = field(default_factory=dict, init=False)
    _catalog_loaded: bool = field(default=False, init=False)
    _sector_ids: list[str] = field(default_factory=list, init=False)
    _stock_symbols: list[str] = field(default_factory=list, init=False)
    _code_to_symbol: dict[str, str] = field(default_factory=dict, init=False)
    _member_counts: dict[str, int] = field(default_factory=dict, init=False)

    def collect(self, trade_date: date, minute: str) -> dict[str, int | str]:
        started_at = time.perf_counter()
        self._ensure_catalog()
        if self._open_minute is not None and self._open_minute != minute:
            self._finalize_minute(trade_date, self._open_minute)
        self._open_minute = minute

        catalog = self.meta.catalog_snapshot()
        if not catalog.catalog_version:
            raise ValueError("catalog version is required before yuntu collection")

        observed_at = datetime.combine(trade_date, datetime.strptime(minute, "%H:%M").time())
        batch_id = f"{trade_date.isoformat()}T{minute}-yuntu"

        try:
            body = fetch_real_hq_script(timeout_seconds=self.settings.enhanced_node_timeout_seconds)
            rows = decode_real_hq_script(body)
        except Exception as error:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return {
                "yuntu_stocks": 0,
                "yuntu_sectors": 0,
                "minute": minute,
                "duration_ms": duration_ms,
                "skipped": str(error),
            }

        stocks = build_stock_minutes_from_yuntu(
            trade_date=trade_date,
            minute=minute,
            rows=rows,
            code_to_symbol=self._code_to_symbol,
            previous_main_cum=self._previous_stock_main_cum,
            observed_at=observed_at,
            batch_id=batch_id,
        )
        sectors = build_sector_minutes_from_yuntu(
            trade_date=trade_date,
            minute=minute,
            rows=rows,
            sector_ids=self._sector_ids,
            member_counts=self._member_counts,
            previous_main_cum=self._previous_sector_main_cum,
            observed_at=observed_at,
            batch_id=batch_id,
        )
        if stocks:
            self.hot.write_stocks(stocks)
            apply_written_main_cum(self._previous_stock_main_cum, stocks, key_attr="symbol")
        if sectors:
            self.hot.write_sectors(sectors)
            apply_written_main_cum(self._previous_sector_main_cum, sectors, key_attr="sector_id")

        market_scopes = build_market_scope_minutes_from_yuntu(
            trade_date=trade_date,
            minute=minute,
            rows=rows,
            previous_main_cum=self._previous_market_scope_main_cum,
            observed_at=observed_at,
            batch_id=batch_id,
        )
        if market_scopes:
            self.hot.write_market_scopes(market_scopes)
            apply_written_main_cum(
                self._previous_market_scope_main_cum,
                market_scopes,
                key_attr="scope",
            )

        self._minutes_with_success.add(minute)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "yuntu_stocks": len(stocks),
            "yuntu_sectors": len(sectors),
            "yuntu_market_scopes": len(market_scopes),
            "minute": minute,
            "duration_ms": duration_ms,
            "source": YUNTU_SOURCE,
        }

    def finalize_pending(self, trade_date: date) -> dict[str, int | str] | None:
        if self._open_minute is None:
            return None
        minute = self._open_minute
        self._finalize_minute(trade_date, minute)
        self._open_minute = None
        return {"finalized_minute": minute}

    def _finalize_minute(self, trade_date: date, minute: str) -> None:
        if minute in self._minutes_with_success:
            return
        self._ensure_catalog()
        observed_at = datetime.combine(trade_date, datetime.strptime(minute, "%H:%M").time())
        batch_id = f"{trade_date.isoformat()}T{minute}-{GAP_BATCH_MARKER}"
        stocks = build_gap_stock_minutes(
            trade_date=trade_date,
            minute=minute,
            symbols=self._stock_symbols,
            previous_main_cum=self._previous_stock_main_cum,
            observed_at=observed_at,
            batch_id=batch_id,
        )
        sectors = build_gap_sector_minutes(
            trade_date=trade_date,
            minute=minute,
            sector_ids=self._sector_ids,
            member_counts=self._member_counts,
            previous_main_cum=self._previous_sector_main_cum,
            observed_at=observed_at,
            batch_id=batch_id,
        )
        if stocks:
            self.hot.write_stocks(stocks)
        if sectors:
            self.hot.write_sectors(sectors)
        market_scopes = build_gap_market_scope_minutes(
            trade_date=trade_date,
            minute=minute,
            previous_main_cum=self._previous_market_scope_main_cum,
            observed_at=observed_at,
            batch_id=batch_id,
        )
        if market_scopes:
            self.hot.write_market_scopes(market_scopes)

    def _ensure_catalog(self) -> None:
        if self._catalog_loaded:
            return
        with self.meta.connect() as connection:
            sector_rows = connection.execute(
                "SELECT sector_id FROM sector_master ORDER BY sector_id"
            ).fetchall()
            security_rows = connection.execute(
                "SELECT symbol, code FROM security_master ORDER BY symbol"
            ).fetchall()
            membership_rows = connection.execute(
                "SELECT sector_id, symbol FROM sector_membership"
            ).fetchall()
        self._sector_ids = [str(row[0]) for row in sector_rows]
        self._stock_symbols = [str(row[0]) for row in security_rows]
        self._code_to_symbol = {str(row[1]): str(row[0]) for row in security_rows}
        member_counts: dict[str, int] = {}
        for sector_id, _symbol in membership_rows:
            key = str(sector_id)
            member_counts[key] = member_counts.get(key, 0) + 1
        self._member_counts = member_counts
        self._catalog_loaded = True
