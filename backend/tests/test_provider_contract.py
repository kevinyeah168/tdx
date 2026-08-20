from datetime import date
from typing import Sequence

from workbench.domain import (
    Bar,
    DataEnvelope,
    OrderBook,
    ProviderCapabilities,
    QuoteSnapshot,
    Transaction,
)
from workbench.providers.base import (
    BarProvider,
    CapabilityProbe,
    CatalogProvider,
    MarketDataProvider,
    MinuteProvider,
    OrderBookProvider,
    QuoteProvider,
    TransactionProvider,
)
from workbench.providers.fake import FakeMarketProvider


class CompleteProvider(FakeMarketProvider):
    def quotes(self, symbols: Sequence[str]) -> DataEnvelope[list[QuoteSnapshot]]:
        raise NotImplementedError

    def transactions(
        self, symbol: str, trade_date: date
    ) -> DataEnvelope[list[Transaction]]:
        raise NotImplementedError

    def bars(self, symbol: str, period: str, count: int) -> DataEnvelope[list[Bar]]:
        raise NotImplementedError

    def order_book(self, symbol: str) -> DataEnvelope[OrderBook]:
        raise NotImplementedError

    def probe_capabilities(self) -> DataEnvelope[ProviderCapabilities]:
        raise NotImplementedError


def test_fake_provider_keeps_catalog_and_minute_contract_compatibility() -> None:
    provider = FakeMarketProvider(stock_count=1, sector_count=0, members_per_sector=0)

    assert isinstance(provider, CatalogProvider)
    assert isinstance(provider, MinuteProvider)
    assert isinstance(provider, MarketDataProvider)
    assert not isinstance(provider, QuoteProvider)
    assert not isinstance(provider, TransactionProvider)
    assert not isinstance(provider, BarProvider)
    assert not isinstance(provider, OrderBookProvider)
    assert not isinstance(provider, CapabilityProbe)


def test_full_provider_contract_is_split_by_data_responsibility() -> None:
    provider = CompleteProvider(stock_count=1, sector_count=0, members_per_sector=0)

    assert isinstance(provider, CatalogProvider)
    assert isinstance(provider, MinuteProvider)
    assert isinstance(provider, QuoteProvider)
    assert isinstance(provider, TransactionProvider)
    assert isinstance(provider, BarProvider)
    assert isinstance(provider, OrderBookProvider)
    assert isinstance(provider, CapabilityProbe)
