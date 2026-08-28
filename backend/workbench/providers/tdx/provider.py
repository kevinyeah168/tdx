from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import json

from workbench.config import WorkbenchSettings
from workbench.domain import Bar, BarPeriod, DataEnvelope, DataQuality, ProviderMinuteBatch
from workbench.providers.base import MarketCatalog
from workbench.providers.tdx.bars import TdxBarService
from workbench.providers.tdx.catalog import CatalogLoadResult, TdxCatalogLoader
from workbench.providers.tdx.board_sectors import OfficialSectorBatchBuilder
from workbench.providers.tdx.fund_flow import (
    apply_estimated_tiers,
    build_minute_batch_from_quotes,
    build_stock_minutes,
)
from workbench.providers.tdx.quotes import TdxQuoteService
from workbench.providers.tdx.transaction_fetcher import TransactionFetcher


class TdxMarketProvider:
    def __init__(
        self,
        settings: WorkbenchSettings,
        *,
        fixture_dir: Path | None = None,
        catalog_loader: TdxCatalogLoader | None = None,
        quote_service: TdxQuoteService | None = None,
        bar_service: TdxBarService | None = None,
        normal_client: object | None = None,
        normal_pool: object | None = None,
        enhanced_pool: object | None = None,
        enhanced_client: object | None = None,
    ) -> None:
        self._settings = settings
        self._fixture_dir = fixture_dir
        self._normal_client = normal_client
        self._normal_pool = normal_pool
        self._enhanced_pool = enhanced_pool
        self._enhanced_client = enhanced_client
        self._catalog_loader = catalog_loader or (
            TdxCatalogLoader.from_fixture_dir(fixture_dir) if fixture_dir is not None else None
        )
        if quote_service is not None:
            self._quote_service = quote_service
        elif fixture_dir is not None:
            quote_rows = json.loads((fixture_dir / "quotes.json").read_text(encoding="utf-8"))
            self._quote_service = TdxQuoteService(settings=settings, fixture_rows=quote_rows)
            self._raw_quote_rows = quote_rows
        else:
            self._quote_service = TdxQuoteService(settings=settings)
            self._raw_quote_rows = []
        if bar_service is not None:
            self._bar_service = bar_service
        elif fixture_dir is not None:
            bar_rows = json.loads((fixture_dir / "bars.json").read_text(encoding="utf-8"))
            self._bar_service = TdxBarService(
                settings,
                fixture_rows={"SH600000": bar_rows},
            )
        else:
            self._bar_service = TdxBarService(settings)
        self._catalog: MarketCatalog | None = None
        self._catalog_result: CatalogLoadResult | None = None
        self._previous_main_cum: dict[str, float] = {}
        self._previous_sector_main_cum: dict[str, float] = {}
        self._previous_amount_cum: dict[str, float] = {}
        self._previous_tier_cum: dict[str, dict[str, float]] = {}
        self._transaction_fetcher = (
            TransactionFetcher(normal_client) if normal_client is not None else None
        )

    @property
    def catalog_result(self) -> CatalogLoadResult | None:
        return self._catalog_result

    def catalog(self) -> MarketCatalog:
        if self._catalog is not None:
            return self._catalog
        if self._catalog_loader is None:
            raise ValueError("catalog loader is required")
        result = self._catalog_loader.load()
        self._catalog_result = result
        if result.stale and not result.catalog.securities:
            raise RuntimeError(result.error_summary or "catalog sync failed")
        self._catalog = result.catalog
        return self._catalog

    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch:
        catalog = self.catalog()
        symbols = [security.symbol for security in catalog.securities]
        observed_at = datetime.combine(trade_date, datetime.strptime(minute, "%H:%M").time())
        if self._fixture_dir is not None:
            rows = [row for row in self._raw_quote_rows if row["symbol"] in symbols]
            stocks = build_stock_minutes(
                trade_date=trade_date,
                minute=minute,
                quote_rows=rows,
                previous_main_cum=self._previous_main_cum,
                previous_amount_cum=self._previous_amount_cum,
                observed_at=observed_at,
            )
            tx_rows = json.loads((self._fixture_dir / "transactions.json").read_text(encoding="utf-8"))
            tx_by_symbol = {symbol: tx_rows for symbol in {stock.symbol for stock in stocks}}
            stocks = apply_estimated_tiers(stocks, tx_by_symbol)
            for stock in stocks:
                self._previous_main_cum[stock.symbol] = stock.funds.main.cumulative
                self._previous_amount_cum[stock.symbol] = (
                    self._previous_amount_cum.get(stock.symbol, 0.0) + stock.amount_delta
                )
            return ProviderMinuteBatch(
                trade_date=trade_date,
                minute=minute,
                stocks=stocks,
                expected_stocks=len(symbols),
            )
        batch = build_minute_batch_from_quotes(
            trade_date=trade_date,
            minute=minute,
            quote_service=self._quote_service,
            symbols=symbols,
            expected_stocks=len(symbols),
            previous_main_cum=self._previous_main_cum,
            previous_amount_cum=self._previous_amount_cum,
            observed_at=observed_at,
        )
        if (
            self._settings.estimate_transaction_tiers
            and self._transaction_fetcher is not None
            and batch.stocks
        ):
            active_symbols = [stock.symbol for stock in batch.stocks[:100]]
            tx_by_symbol = self._transaction_fetcher.fetch_batch(
                active_symbols,
                shard_count=1,
            )
            enriched = apply_estimated_tiers(
                batch.stocks,
                tx_by_symbol,
                previous_tier_cum=self._previous_tier_cum,
            )
            for stock in enriched:
                self._previous_tier_cum[stock.symbol] = {
                    "super": stock.funds.super.cumulative,
                    "large": stock.funds.large.cumulative,
                    "medium": stock.funds.medium.cumulative,
                    "small": stock.funds.small.cumulative,
                }
            enriched_batch = ProviderMinuteBatch(
                trade_date=batch.trade_date,
                minute=batch.minute,
                stocks=enriched,
                expected_stocks=batch.expected_stocks,
            )
            return self._attach_official_sectors(enriched_batch, catalog, observed_at)
        return self._attach_official_sectors(batch, catalog, observed_at)

    def _attach_official_sectors(
        self,
        batch: ProviderMinuteBatch,
        catalog: MarketCatalog,
        observed_at: datetime,
    ) -> ProviderMinuteBatch:
        if (
            not self._settings.sector_official_main_enabled
            or self._enhanced_client is None
            or not catalog.sectors
        ):
            return batch

        member_counts: dict[str, int] = {}
        for membership in catalog.memberships:
            member_counts[membership.sector_id] = member_counts.get(membership.sector_id, 0) + 1

        board_page_size = getattr(self._catalog_loader, "_board_page_size", 10_000)
        builder = OfficialSectorBatchBuilder(
            settings=self._settings,
            get_board_list=self._enhanced_client.get_board_list,
            get_stock_quotes=getattr(self._enhanced_client, "get_stock_quotes", None),
            board_page_size=board_page_size,
            previous_main_cum=self._previous_sector_main_cum,
        )
        sectors, sector_errors = builder.build(
            trade_date=batch.trade_date,
            minute=batch.minute,
            sectors=catalog.sectors,
            member_counts=member_counts,
            observed_at=observed_at,
        )
        return batch.model_copy(
            update={
                "sectors": sectors,
                "expected_sectors": len(catalog.sectors),
                "errors": [*batch.errors, *sector_errors],
            }
        )

    def bars(
        self, symbol: str, period: BarPeriod, count: int
    ) -> DataEnvelope[list[Bar]]:
        bars = self._bar_service.fetch_bars(symbol, period, count)
        if not bars:
            return DataEnvelope(
                data=None,
                source="tdx.bars",
                quality=DataQuality.GAP,
                observed_at=datetime.now(),
                catalog_version=self.catalog().version,
                gap_reason="bars unavailable for symbol",
            )
        return DataEnvelope(
            data=bars,
            source="tdx.bars",
            quality=DataQuality.OFFICIAL,
            observed_at=datetime.now(),
            catalog_version=self.catalog().version,
        )

    def close(self) -> None:
        for pool in (self._normal_pool, self._enhanced_pool):
            if pool is None:
                continue
            close = getattr(pool, "close", None)
            if callable(close):
                close()
