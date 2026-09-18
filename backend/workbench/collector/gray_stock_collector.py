from __future__ import annotations

import time
from datetime import date, datetime

from workbench.collector.sector_gray_aggregator import SectorGrayAggregator
from workbench.config import WorkbenchSettings
from workbench.domain import StockGrayMinute
from workbench.providers.eastmoney.gray_flow_minutes import (
    format_gray_flow_minute,
    normalize_gray_flow_sampled_at,
)
from workbench.providers.eastmoney.gray_market import GrayMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


class GrayStockCollector:
    """Poll East Money darktrade full-market leaderboard on a fixed interval."""

    def __init__(
        self,
        hot: HotStore,
        *,
        settings: WorkbenchSettings,
        gray_provider: GrayMarketProvider | None = None,
        meta: MetaStore | None = None,
        sector_gray_aggregator: SectorGrayAggregator | None = None,
    ) -> None:
        self.hot = hot
        self._settings = settings
        self._gray = gray_provider or GrayMarketProvider()
        self._meta = meta
        self._sector_gray = sector_gray_aggregator

    def _resolve_sector_gray_aggregator(self) -> SectorGrayAggregator | None:
        if self._sector_gray is not None:
            return self._sector_gray
        if self._meta is None:
            return None
        memberships = self._meta.all_memberships()
        if not memberships:
            return None
        self._sector_gray = SectorGrayAggregator(memberships)
        return self._sector_gray

    def collect(self, trade_date: date, _minute: str | None = None) -> dict[str, int | str]:
        started_at = time.perf_counter()
        try:
            samples = self._gray.fetch_full_market_gray_snapshots(
                trade_date=trade_date.isoformat(),
            )
        except Exception as error:
            return {"gray_stocks": 0, "gray_sectors": 0, "minute": "", "skipped": str(error)}

        # Bucket by wall-clock minute at write time so 15s polls upsert the same minute
        # until the clock rolls over, then start a fresh minute row (ON CONFLICT upsert).
        observed_at = normalize_gray_flow_sampled_at(datetime.now())
        bucket_minute = format_gray_flow_minute(observed_at)
        batch_id = f"{trade_date.isoformat()}T{bucket_minute}-gray-market"

        records: list[StockGrayMinute] = []
        for sample in samples:
            records.append(
                StockGrayMinute(
                    trade_date=trade_date,
                    minute=bucket_minute,
                    symbol=sample.symbol.upper(),
                    code=sample.code,
                    open_cum=sample.open_net_inflow,
                    dark_cum=sample.dark_net_inflow,
                    total_cum=sample.total_net_inflow,
                    observed_at=observed_at,
                    batch_id=batch_id,
                    source=sample.source,
                )
            )
        if records:
            self.hot.write_stock_gray(records)

        sector_records = []
        aggregator = self._resolve_sector_gray_aggregator()
        if aggregator is not None and records:
            sector_records = aggregator.aggregate(
                records,
                trade_date=trade_date,
                minute=bucket_minute,
                observed_at=observed_at,
                batch_id=batch_id,
            )
            if sector_records:
                self.hot.write_sector_gray(sector_records)

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "gray_stocks": len(records),
            "gray_sectors": len(sector_records),
            "minute": bucket_minute,
            "duration_ms": duration_ms,
        }
