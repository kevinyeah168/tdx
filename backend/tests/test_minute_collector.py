from datetime import date
from pathlib import Path
import time

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
    assert result["catalog_version"] == "fake-v1"
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


def test_collector_uses_one_catalog_snapshot_instead_of_separate_reads(tmp_path: Path) -> None:
    class SnapshotOnlyMetaStore(MetaStore):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self.snapshot_calls = 0

        def catalog_snapshot(self):  # type: ignore[no-untyped-def]
            self.snapshot_calls += 1
            return super().catalog_snapshot()

        def all_memberships(self):  # type: ignore[no-untyped-def]
            raise AssertionError("collector must use catalog_snapshot")

        def sector_count(self):  # type: ignore[no-untyped-def]
            raise AssertionError("collector must use catalog_snapshot")

    provider = FakeMarketProvider(1, 1, 1)
    meta = SnapshotOnlyMetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(tmp_path / "2026-08-20.sqlite")
    hot.initialize()

    result = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    assert meta.snapshot_calls == 1
    assert result["expected_sectors"] == 1
    assert result["catalog_version"] == "fake-v1"


def test_collector_handles_5500_stock_400_sector_batch_within_budget(tmp_path: Path) -> None:
    provider = FakeMarketProvider(5_500, 400, 80)
    meta, hot = stores(tmp_path, provider)
    started_at = time.perf_counter()

    result = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    assert time.perf_counter() - started_at < 45
    assert result["collected_stocks"] == 5_500
    assert result["collected_sectors"] == 400
