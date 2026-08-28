from __future__ import annotations

import time
from datetime import date, datetime

from workbench.collector.priority_targets import refresh_priority_stock_targets
from workbench.config import WorkbenchSettings
from workbench.providers.base import MarketDataProvider
from workbench.providers.tdx.fund_flow import build_stock_minutes
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


class PriorityStockCollector:
    """Fast path: refresh main/change for linkage + priority-sector members + manual picks."""

    def __init__(
        self,
        provider: MarketDataProvider,
        meta: MetaStore,
        hot: HotStore,
        *,
        settings: WorkbenchSettings,
    ) -> None:
        self.provider = provider
        self.meta = meta
        self.hot = hot
        self._settings = settings
        self._previous_main_cum: dict[str, float] = {}
        self._previous_amount_cum: dict[str, float] = {}

    def collect(self, trade_date: date, minute: str) -> dict[str, int | str]:
        started_at = time.perf_counter()
        enhanced = getattr(self.provider, "_enhanced_client", None)
        symbols = refresh_priority_stock_targets(
            self._settings,
            self.meta,
            enhanced_client=enhanced,
        )
        if not symbols:
            return {"priority_stocks": 0, "minute": minute, "skipped": "empty-targets"}

        quote_service = getattr(self.provider, "_quote_service", None)
        if quote_service is None:
            return {"priority_stocks": 0, "minute": minute, "skipped": "no-quote-service"}

        catalog = self.meta.catalog_snapshot()
        if not catalog.catalog_version:
            raise ValueError("catalog version is required before priority stock collection")

        observed_at = datetime.combine(trade_date, datetime.strptime(minute, "%H:%M").time())
        batch_id = f"{trade_date.isoformat()}T{minute}-priority"
        quote_rows = quote_service.fetch_quote_rows(symbols)
        stocks = build_stock_minutes(
            trade_date=trade_date,
            minute=minute,
            quote_rows=quote_rows,
            previous_main_cum=self._previous_main_cum,
            previous_amount_cum=self._previous_amount_cum,
            observed_at=observed_at,
            batch_id=batch_id,
        )
        if stocks:
            self.hot.write_stocks(stocks)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "priority_stocks": len(stocks),
            "minute": minute,
            "duration_ms": duration_ms,
        }
