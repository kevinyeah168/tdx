from __future__ import annotations

from datetime import datetime, timezone

from workbench.providers.base import MarketDataProvider
from workbench.providers.tdx.catalog import CatalogLoadResult
from workbench.storage.meta_store import MetaStore


class CatalogSyncService:
    def __init__(self, provider: MarketDataProvider, store: MetaStore) -> None:
        self.provider = provider
        self.store = store

    def sync(self, *, force: bool = False) -> dict[str, int | str | bool | None]:
        if not force and self.store.catalog_version() is not None:
            snapshot = self.store.catalog_snapshot()
            return {
                "securities": self.store.security_count(),
                "sectors": self.store.sector_count(),
                "memberships": len(self.store.all_memberships()),
                "stale": snapshot.stale,
                "error_summary": snapshot.error_summary,
                "skipped": True,
            }
        catalog_result: CatalogLoadResult | None = getattr(
            self.provider, "catalog_result", None
        )
        try:
            catalog = self.provider.catalog()
        except RuntimeError as error:
            if catalog_result is not None and catalog_result.stale:
                self.store.mark_catalog_stale(
                    error_summary=catalog_result.error_summary or str(error),
                    source=catalog_result.source,
                )
                return {
                    "securities": self.store.security_count(),
                    "sectors": self.store.sector_count(),
                    "memberships": len(self.store.all_memberships()),
                    "stale": True,
                    "error_summary": catalog_result.error_summary or str(error),
                }
            raise
        synced_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        source = catalog_result.source if catalog_result is not None else "provider.catalog"
        self.store.replace_catalog(
            securities=catalog.securities,
            sectors=catalog.sectors,
            memberships=catalog.memberships,
            version=catalog.version,
            synced_at=synced_at,
            source=source,
            stale=catalog_result.stale if catalog_result is not None else False,
            error_summary=catalog_result.error_summary if catalog_result is not None else None,
        )
        return {
            "securities": len(catalog.securities),
            "sectors": len(catalog.sectors),
            "memberships": len(catalog.memberships),
            "stale": catalog_result.stale if catalog_result is not None else False,
            "error_summary": catalog_result.error_summary if catalog_result is not None else None,
        }
