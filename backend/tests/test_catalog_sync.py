from pathlib import Path

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.providers.base import MarketCatalog
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.meta_store import MetaStore


def test_sync_persists_fake_provider_catalog_and_returns_counts(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()

    result = CatalogSyncService(FakeMarketProvider(12, 3, 4), store).sync()

    assert result == {"securities": 12, "sectors": 3, "memberships": 12}
    assert store.catalog_version() is not None
    assert store.security_count() == 12
    assert store.sector_count() == 3


def test_sync_replaces_previous_catalog_version_without_stale_rows(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    first_catalog = FakeMarketProvider(12, 3, 4).catalog().model_copy(update={"version": "v1"})
    second_catalog = FakeMarketProvider(2, 1, 1).catalog().model_copy(update={"version": "v2"})

    CatalogSyncService(CatalogProvider(first_catalog), store).sync()
    result = CatalogSyncService(CatalogProvider(second_catalog), store).sync()

    assert result == {"securities": 2, "sectors": 1, "memberships": 1}
    assert store.catalog_version() == "v2"
    assert store.security_count() == 2
    assert store.sector_count() == 1
    assert len(store.all_memberships()) == 1


class CatalogProvider:
    def __init__(self, catalog: MarketCatalog) -> None:
        self._catalog = catalog

    def catalog(self) -> MarketCatalog:
        return self._catalog
