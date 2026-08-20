from datetime import date
from typing import Sequence

from workbench.domain import (
    Bar,
    BarPeriod,
    DataEnvelope,
    OrderBook,
    ProviderCapabilities,
    ProviderMinuteBatch,
    QuoteSnapshot,
    Transaction,
)
from workbench.providers.base import (
    BarProvider,
    CapabilityProbe,
    CatalogProvider,
    MarketCatalog,
    MinuteProvider,
    OrderBookProvider,
    QuoteProvider,
    TransactionProvider,
)


class GoodProvider:
    def catalog(self) -> MarketCatalog:
        raise NotImplementedError

    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch:
        raise NotImplementedError

    def quotes(self, symbols: Sequence[str]) -> DataEnvelope[list[QuoteSnapshot]]:
        raise NotImplementedError

    def transactions(
        self, symbol: str, trade_date: date
    ) -> DataEnvelope[list[Transaction]]:
        raise NotImplementedError

    def bars(
        self, symbol: str, period: BarPeriod, count: int
    ) -> DataEnvelope[list[Bar]]:
        raise NotImplementedError

    def order_book(self, symbol: str) -> DataEnvelope[OrderBook]:
        raise NotImplementedError

    def probe_capabilities(self) -> DataEnvelope[ProviderCapabilities]:
        raise NotImplementedError


provider = GoodProvider()
catalog_provider: CatalogProvider = provider
minute_provider: MinuteProvider = provider
quote_provider: QuoteProvider = provider
transaction_provider: TransactionProvider = provider
bar_provider: BarProvider = provider
order_book_provider: OrderBookProvider = provider
capability_probe: CapabilityProbe = provider
