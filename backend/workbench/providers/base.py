from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import model_validator

from workbench.domain import (
    Membership,
    NonBlankText,
    NormalizedModel,
    ProviderMinuteBatch,
    Sector,
    Security,
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


class MarketDataProvider(Protocol):
    def catalog(self) -> MarketCatalog: ...

    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch: ...
