from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from workbench.config import WorkbenchSettings
from workbench.domain import DataQuality, FundFlow, StockGrayMinute, StockMinute, TierPoint
from workbench.query.custom_sector_flow import CustomSectorFlowService
from workbench.services.custom_sectors import CustomSectorService
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore

TRADE_DATE = date(2026, 8, 20)


def _stock_minute(symbol: str, minute: str, main_cum: float) -> StockMinute:
    tier = TierPoint(delta=main_cum / 10, cumulative=main_cum, source="test", quality=DataQuality.OFFICIAL)
    return StockMinute(
        trade_date=TRADE_DATE,
        minute=minute,
        symbol=symbol,
        close=10.0,
        change_pct=1.0,
        amount_delta=1_000_000.0,
        funds=FundFlow(main=tier, super=tier, large=tier, medium=tier, small=tier),
        observed_at=datetime(2026, 8, 20, 9, 31),
        batch_id="test",
    )


def _seed_custom_sector_flow(tmp_path: Path) -> str:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    service = CustomSectorService(meta)
    sector = service.create_sector("测试板块")
    service.add_members(sector.sector_id, ["SH600000", "SZ000001"])

    settings = WorkbenchSettings(data_dir=tmp_path)
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    hot.initialize()
    hot.write_stocks(
        [
            _stock_minute("SH600000", "09:31", 100.0),
            _stock_minute("SH600000", "09:32", 120.0),
            _stock_minute("SZ000001", "09:31", 50.0),
            _stock_minute("SZ000001", "09:32", 80.0),
        ]
    )
    hot.write_stock_gray(
        [
            StockGrayMinute(
                trade_date=TRADE_DATE,
                minute="09:31",
                symbol="SH600000",
                code="600000",
                open_cum=10.0,
                dark_cum=100.0,
                total_cum=110.0,
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id="test-gray",
                source="eastmoney:graymarket:darktrade",
            ),
            StockGrayMinute(
                trade_date=TRADE_DATE,
                minute="09:31",
                symbol="SZ000001",
                code="000001",
                open_cum=5.0,
                dark_cum=20.0,
                total_cum=25.0,
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id="test-gray",
                source="eastmoney:graymarket:darktrade",
            ),
        ]
    )
    return sector.sector_id


def test_custom_sector_fund_and_gray_aggregation(tmp_path: Path) -> None:
    sector_id = _seed_custom_sector_flow(tmp_path)
    settings = WorkbenchSettings(data_dir=tmp_path)
    meta = MetaStore(tmp_path / "meta.sqlite")
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    flow = CustomSectorFlowService(meta, hot)

    fund_curve = flow.complete_fund_curve(TRADE_DATE.isoformat(), sector_id)
    assert [row["minute"] for row in fund_curve.rows] == ["09:31", "09:32"]
    assert fund_curve.rows[0]["main_cum"] == 150.0
    assert fund_curve.rows[1]["main_cum"] == 200.0

    gray_curve = flow.sector_gray_curve(TRADE_DATE.isoformat(), sector_id)
    assert len(gray_curve.rows) == 1
    assert gray_curve.rows[0]["dark_cum"] == 120.0
    assert gray_curve.rows[0]["gray_covered_count"] == 2


def test_custom_sector_fund_tip_at_minute(tmp_path: Path) -> None:
    sector_id = _seed_custom_sector_flow(tmp_path)
    settings = WorkbenchSettings(data_dir=tmp_path)
    meta = MetaStore(tmp_path / "meta.sqlite")
    hot = HotStore(settings.hot_db_for(TRADE_DATE.isoformat()))
    flow = CustomSectorFlowService(meta, hot)

    tip = flow.fund_tip_at_minute(TRADE_DATE.isoformat(), sector_id, "09:32")
    assert tip is not None
    assert tip["minute"] == "09:32"
    assert tip["main_cum"] == 200.0
