from datetime import date
from pathlib import Path

import pytest

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.domain import ProviderMinuteBatch
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def stores(tmp_path: Path, provider: FakeMarketProvider) -> tuple[MetaStore, HotStore]:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(tmp_path / "2026-08-20.sqlite")
    hot.initialize()
    return meta, hot


def test_collector_commits_complete_market_minute_atomically(tmp_path: Path) -> None:
    provider = FakeMarketProvider(100, 4, 20)
    meta, hot = stores(tmp_path, provider)

    result = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    assert result["collected_stocks"] == 100
    assert result["collected_sectors"] == 4
    assert result["coverage_pct"] == 100.0
    assert result["status"] == "complete"
    assert isinstance(result["duration_ms"], int)
    assert hot.latest_complete_minute("2026-08-20") == "09:31"
    assert len(hot.stock_fund_series("2026-08-20", "SH600000")) == 1
    assert len(hot.sector_fund_series("2026-08-20", "880000")) == 1


def test_partial_batch_does_not_advance_latest_complete_minute(tmp_path: Path) -> None:
    class PartialProvider(FakeMarketProvider):
        def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch:
            batch = super().minute_batch(trade_date, minute)
            return batch.model_copy(update={"stocks": batch.stocks[:-1]})

    provider = PartialProvider(100, 4, 20)
    meta, hot = stores(tmp_path, provider)

    result = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    assert result["coverage_pct"] == 99.0
    assert result["status"] == "partial"
    assert hot.latest_complete_minute("2026-08-20") is None


def test_collector_rejects_provider_batch_identity_mismatch_before_persistence(tmp_path: Path) -> None:
    class MismatchedProvider(FakeMarketProvider):
        def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch:
            batch = super().minute_batch(trade_date, minute)
            return batch.model_copy(update={"minute": "09:32"})

    provider = MismatchedProvider(1, 1, 1)
    meta, hot = stores(tmp_path, provider)

    with pytest.raises(ValueError, match="requested trade_date and minute"):
        MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    assert hot.stock_fund_series("2026-08-20", "SH600000") == []
    assert hot.latest_complete_minute("2026-08-20") is None


def test_zero_sector_catalog_is_complete_when_stock_coverage_is_sufficient(tmp_path: Path) -> None:
    provider = FakeMarketProvider(1, 0, 0)
    meta, hot = stores(tmp_path, provider)

    result = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    assert result["expected_sectors"] == 0
    assert result["collected_sectors"] == 0
    assert result["status"] == "complete"
