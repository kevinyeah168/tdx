from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel

from workbench.domain import Membership, ProviderMinuteBatch, Sector, Security


class MarketCatalog(BaseModel):
    securities: list[Security]
    sectors: list[Sector]
    memberships: list[Membership]
    version: str


class MarketDataProvider(Protocol):
    def catalog(self) -> MarketCatalog: ...

    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch: ...
