from __future__ import annotations

import time
from datetime import date, datetime

from workbench.collector.priority_linkage import read_linkage_sector_id, read_linkage_sector_name
from workbench.collector.priority_sectors import read_priority_sector_ids
from workbench.query.sector_resolve import resolve_member_sector_id
from workbench.providers.base import MarketDataProvider
from workbench.providers.tdx.board_sectors import OfficialSectorBatchBuilder
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


class PrioritySectorCollector:
    """Fast path: refresh official sector main/change for selected + rank pool only."""

    def __init__(
        self,
        provider: MarketDataProvider,
        meta: MetaStore,
        hot: HotStore,
        *,
        data_dir,
        rank_pool: int = 40,
        max_sectors: int = 80,
    ) -> None:
        self.provider = provider
        self.meta = meta
        self.hot = hot
        self._data_dir = data_dir
        self._rank_pool = max(0, rank_pool)
        self._max_sectors = max(1, max_sectors)
        self._previous_main_cum: dict[str, float] = {}

    def collect(self, trade_date: date, minute: str) -> dict[str, int | str]:
        started_at = time.perf_counter()
        sector_ids = self._resolve_sector_ids_for_minute(trade_date, minute)
        if not sector_ids:
            return {"priority_sectors": 0, "minute": minute, "skipped": "empty-targets"}

        catalog = self.meta.catalog_snapshot()
        if not catalog.catalog_version:
            raise ValueError("catalog version is required before priority collection")

        by_id = {sector.sector_id: sector for sector in self.provider.catalog().sectors}
        targets = [by_id[sid] for sid in sector_ids if sid in by_id]
        if not targets:
            return {"priority_sectors": 0, "minute": minute, "skipped": "no-catalog-match"}

        enhanced = getattr(self.provider, "_enhanced_client", None)
        if enhanced is None:
            return {"priority_sectors": 0, "minute": minute, "skipped": "no-enhanced-client"}

        member_counts: dict[str, int] = {}
        for membership in self.provider.catalog().memberships:
            member_counts[membership.sector_id] = member_counts.get(membership.sector_id, 0) + 1

        board_page_size = getattr(getattr(self.provider, "_catalog_loader", None), "_board_page_size", 10_000)
        builder = OfficialSectorBatchBuilder(
            settings=getattr(self.provider, "_settings"),
            get_board_list=enhanced.get_board_list,
            get_stock_quotes=getattr(enhanced, "get_stock_quotes", None),
            board_page_size=board_page_size,
            previous_main_cum=self._previous_main_cum,
        )
        observed_at = datetime.combine(trade_date, datetime.strptime(minute, "%H:%M").time())
        sectors, errors = builder.build(
            trade_date=trade_date,
            minute=minute,
            sectors=targets,
            member_counts=member_counts,
            observed_at=observed_at,
        )
        if sectors:
            self.hot.write_sectors(sectors)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "priority_sectors": len(sectors),
            "minute": minute,
            "duration_ms": duration_ms,
            "errors": len(errors),
        }

    def _resolve_sector_ids(self, trade_date: date) -> list[str]:
        latest = self.hot.latest_sector_minute(trade_date.isoformat()) or "09:31"
        return self._resolve_sector_ids_for_minute(trade_date, latest)

    def _resolve_sector_ids_for_minute(self, trade_date: date, minute: str) -> list[str]:
        selected = read_priority_sector_ids(self._data_dir)
        ranked = self._top_sector_ids_from_hot(trade_date.isoformat(), minute, self._rank_pool)
        linkage_raw = read_linkage_sector_id(self._data_dir)
        linkage_resolved = None
        if linkage_raw:
            linkage_resolved = resolve_member_sector_id(
                self.meta,
                linkage_raw,
                sector_name=read_linkage_sector_name(self._data_dir),
            )
        merged: list[str] = []
        seen: set[str] = set()
        for sector_id in [linkage_resolved, *selected, *ranked]:
            if not sector_id or sector_id in seen:
                continue
            seen.add(sector_id)
            merged.append(sector_id)
            if len(merged) >= self._max_sectors:
                break
        return merged

    def _top_sector_ids_from_hot(self, trade_date: str, minute: str, limit: int) -> list[str]:
        if limit <= 0:
            return []
        rank_minute = minute
        with self.hot.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM sector_minute WHERE trade_date=? AND minute=? LIMIT 1",
                (trade_date, rank_minute),
            ).fetchone()
            if row is None:
                latest = self.hot.latest_sector_minute(trade_date)
                if not latest:
                    return []
                rank_minute = latest
            rows = connection.execute(
                """
                SELECT sector_id
                FROM sector_minute
                WHERE trade_date=? AND minute=?
                ORDER BY main_cum DESC, sector_id
                LIMIT ?
                """,
                (trade_date, rank_minute, limit),
            ).fetchall()
        return [str(row[0]) for row in rows]
