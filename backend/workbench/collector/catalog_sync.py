from __future__ import annotations

from workbench.providers.base import MarketDataProvider
from workbench.storage.meta_store import MetaStore


class CatalogSyncService:
    def __init__(self, provider: MarketDataProvider, store: MetaStore) -> None:
        self.provider = provider
        self.store = store

    def sync(self) -> dict[str, int]:
        catalog = self.provider.catalog()
        self.store.replace_catalog(
            securities=catalog.securities,
            sectors=catalog.sectors,
            memberships=catalog.memberships,
            version=catalog.version,
        )
        return {
            "securities": len(catalog.securities),
            "sectors": len(catalog.sectors),
            "memberships": len(catalog.memberships),
        }
