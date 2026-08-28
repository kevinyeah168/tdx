from __future__ import annotations

from datetime import date

from workbench.query.models import MarketOverview, QueryMetadata, SearchResponse, SearchResultItem
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


class MarketQueryService:
    def __init__(self, meta: MetaStore, hot: HotStore | None = None) -> None:
        self._meta = meta
        self._hot = hot

    def overview(self, trade_date: date, minute: str | None = None) -> MarketOverview:
        snapshot = self._meta.catalog_snapshot()
        latest_complete_minute = None
        latest_available_minute = None
        if self._hot is not None:
            trade_key = trade_date.isoformat()
            latest_complete_minute = self._hot.latest_complete_minute(trade_key)
            latest_available_minute = self._hot.latest_available_minute(trade_key)
        return MarketOverview(
            trade_date=trade_date.isoformat(),
            minute=minute,
            security_count=self._meta.security_count(),
            sector_count=self._meta.sector_count(),
            latest_complete_minute=latest_complete_minute,
            latest_available_minute=latest_available_minute,
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source,
            ),
        )

    def search(self, query: str, *, limit: int = 20) -> SearchResponse:
        normalized = query.strip()
        snapshot = self._meta.catalog_snapshot()
        with self._meta.connect() as connection:
            rows = connection.execute(
                "SELECT symbol, name, market FROM security_master "
                "WHERE symbol LIKE ? OR name LIKE ? "
                "ORDER BY symbol LIMIT ?",
                (f"%{normalized}%", f"%{normalized}%", limit),
            ).fetchall()
        return SearchResponse(
            query=normalized,
            results=[
                SearchResultItem(symbol=row[0], name=row[1], market=row[2]) for row in rows
            ],
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source,
            ),
        )
