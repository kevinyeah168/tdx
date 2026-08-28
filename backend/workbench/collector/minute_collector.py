from __future__ import annotations

import time
from datetime import date

from workbench.collector.heartbeat import write_collector_heartbeat
from workbench.collector.sector_aggregator import SectorAggregator
from workbench.domain import CollectionStatus
from workbench.providers.base import MarketDataProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


class MinuteCollector:
    def __init__(self, provider: MarketDataProvider, meta: MetaStore, hot: HotStore) -> None:
        self.provider = provider
        self.meta = meta
        self.hot = hot

    def collect(self, trade_date: date, minute: str) -> dict[str, int | float | str]:
        started_at = time.perf_counter()
        batch = self.provider.minute_batch(trade_date, minute)
        if batch.trade_date != trade_date or batch.minute != minute:
            raise ValueError("provider batch must match requested trade_date and minute")

        catalog = self.meta.catalog_snapshot()
        if catalog.catalog_version is None:
            raise ValueError("catalog version is required before minute collection")
        if batch.sectors is not None and batch.sectors:
            sectors = batch.sectors
        else:
            sectors = SectorAggregator(catalog.memberships).aggregate(batch.stocks)
        coverage_pct = (
            round(len(batch.stocks) / batch.expected_stocks * 100.0, 4)
            if batch.expected_stocks
            else 0.0
        )
        sector_complete = catalog.sector_count == len(sectors)
        status = CollectionStatus(
            trade_date=trade_date,
            minute=minute,
            batch_id=f"{trade_date.isoformat()}T{minute}",
            catalog_version=catalog.catalog_version,
            expected_stocks=batch.expected_stocks,
            collected_stocks=len(batch.stocks),
            expected_sectors=catalog.sector_count,
            collected_sectors=len(sectors),
            duration_ms=0,
            coverage_pct=coverage_pct,
            status="complete" if coverage_pct >= 99.5 and sector_complete else "partial",
            error_summary=" | ".join(batch.errors),
        )
        result = self.hot.write_complete_batch(batch.stocks, sectors, status, started_at=started_at)
        write_collector_heartbeat(self.meta.path.parent.parent)
        return result
