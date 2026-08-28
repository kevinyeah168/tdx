from datetime import date, datetime, time

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.domain import DataQuality, FundFlow, ProviderMinuteBatch, SectorMinute, TierPoint
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def _official_sector_minute(sector_id: str) -> SectorMinute:
    return SectorMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        sector_id=sector_id,
        change_pct=-3.13,
        member_count=184,
        funds=FundFlow(
            main=TierPoint(
                delta=-1.0,
                cumulative=-163.0,
                source="tdx.enhanced.board_summary",
                quality=DataQuality.OFFICIAL,
            ),
            super=TierPoint(delta=0.0, cumulative=0.0, source="gap", quality=DataQuality.GAP),
            large=TierPoint(delta=0.0, cumulative=0.0, source="gap", quality=DataQuality.GAP),
            medium=TierPoint(delta=0.0, cumulative=0.0, source="gap", quality=DataQuality.GAP),
            small=TierPoint(delta=0.0, cumulative=0.0, source="gap", quality=DataQuality.GAP),
        ),
        observed_at=datetime.combine(date(2026, 8, 20), time.fromisoformat("09:31")),
        batch_id="2026-08-20T09:31",
    )


def test_collector_prefers_official_sectors_from_provider_batch(tmp_path) -> None:
    class OfficialSectorProvider(FakeMarketProvider):
        def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch:
            batch = super().minute_batch(trade_date, minute)
            return batch.model_copy(
                update={
                    "sectors": [_official_sector_minute("880000")],
                    "expected_sectors": 1,
                }
            )

    provider = OfficialSectorProvider(100, 1, 20)
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(tmp_path / "2026-08-20.sqlite")
    hot.initialize()

    MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    series = hot.sector_fund_series("2026-08-20", "880000")
    assert len(series) == 1
    assert series[0]["main_cum"] == -163.0
