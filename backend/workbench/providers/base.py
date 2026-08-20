from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

from pydantic import model_validator

from workbench.domain import (
    Bar,
    BarPeriod,
    DataEnvelope,
    Membership,
    NonBlankText,
    NormalizedModel,
    OrderBook,
    ProviderCapabilities,
    ProviderMinuteBatch,
    QuoteSnapshot,
    Sector,
    Security,
    Transaction,
)


class MarketCatalog(NormalizedModel):
    securities: list[Security]
    sectors: list[Sector]
    memberships: list[Membership]
    version: NonBlankText

    @model_validator(mode="after")
    def validate_references(self) -> "MarketCatalog":
        security_symbols = {security.symbol for security in self.securities}
        sector_ids = {sector.sector_id for sector in self.sectors}
        membership_pairs = {
            (membership.sector_id, membership.symbol) for membership in self.memberships
        }
        if len(security_symbols) != len(self.securities):
            raise ValueError("securities cannot contain duplicate symbols")
        if len(sector_ids) != len(self.sectors):
            raise ValueError("sectors cannot contain duplicate sector IDs")
        if len(membership_pairs) != len(self.memberships):
            raise ValueError("memberships cannot contain duplicate pairs")
        if any(membership.symbol not in security_symbols for membership in self.memberships):
            raise ValueError("memberships must reference catalog securities")
        if any(membership.sector_id not in sector_ids for membership in self.memberships):
            raise ValueError("memberships must reference catalog sectors")
        return self


@runtime_checkable
class CatalogProvider(Protocol):
    def catalog(self) -> MarketCatalog: ...


@runtime_checkable
class MinuteProvider(Protocol):
    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch: ...


@runtime_checkable
class QuoteProvider(Protocol):
    def quotes(self, symbols: Sequence[str]) -> DataEnvelope[list[QuoteSnapshot]]: ...


@runtime_checkable
class TransactionProvider(Protocol):
    def transactions(
        self, symbol: str, trade_date: date
    ) -> DataEnvelope[list[Transaction]]: ...


@runtime_checkable
class BarProvider(Protocol):
    def bars(
        self, symbol: str, period: BarPeriod, count: int
    ) -> DataEnvelope[list[Bar]]: ...


@runtime_checkable
class OrderBookProvider(Protocol):
    def order_book(self, symbol: str) -> DataEnvelope[OrderBook]: ...


@runtime_checkable
class CapabilityProbe(Protocol):
    def probe_capabilities(self) -> DataEnvelope[ProviderCapabilities]: ...


@runtime_checkable
class MarketDataProvider(CatalogProvider, MinuteProvider, Protocol):
    pass
