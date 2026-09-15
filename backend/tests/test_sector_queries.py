from __future__ import annotations

from datetime import date
from pathlib import Path

from workbench.domain import Membership, Sector, Security
from workbench.query.sectors import SectorQueryService
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def seed_demo_meta_and_hot(tmp_path: Path) -> tuple[MetaStore, HotStore]:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    meta.replace_catalog(
        securities=[
            Security(symbol="SH600000", code="600000", name="浦发银行", market="SH"),
            Security(symbol="SZ000001", code="000001", name="平安银行", market="SZ"),
        ],
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=[
            Membership(sector_id="881001", symbol="SH600000"),
            Membership(sector_id="881001", symbol="SZ000001"),
        ],
        version="catalog-test",
        source="test",
    )
    hot = HotStore(tmp_path / "hot.sqlite")
    hot.initialize()
    return meta, hot


def test_sector_member_ranking_orders_by_main_cumulative(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    from workbench.domain import DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
    from datetime import datetime

    def tier(delta: float, cumulative: float) -> TierPoint:
        return TierPoint(delta=delta, cumulative=cumulative, source="test", quality=DataQuality.OFFICIAL)

    trade_date = date(2026, 8, 20)
    minute = "09:31"
    batch_id = "2026-08-20T09:31"
    stocks = [
        StockMinute(
            trade_date=trade_date,
            minute=minute,
            symbol="SH600000",
            close=10.0,
            change_pct=1.0,
            amount_delta=1000,
            funds=FundFlow(
                main=tier(100, 300),
                super=tier(0, 0),
                large=tier(0, 0),
                medium=tier(0, 0),
                small=tier(0, 0),
            ),
            observed_at=datetime(2026, 8, 20, 9, 31),
            batch_id=batch_id,
        ),
        StockMinute(
            trade_date=trade_date,
            minute=minute,
            symbol="SZ000001",
            close=12.0,
            change_pct=2.0,
            amount_delta=2000,
            funds=FundFlow(
                main=tier(200, 500),
                super=tier(0, 0),
                large=tier(0, 0),
                medium=tier(0, 0),
                small=tier(0, 0),
            ),
            observed_at=datetime(2026, 8, 20, 9, 31),
            batch_id=batch_id,
        ),
    ]
    from workbench.domain import CollectionStatus

    hot.write_complete_batch(
        stocks,
        [
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id="881001",
                change_pct=1.5,
                member_count=2,
                funds=FundFlow(
                    main=tier(300, 800),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            )
        ],
        CollectionStatus(
            trade_date=trade_date,
            minute=minute,
            batch_id=batch_id,
            catalog_version="catalog-test",
            expected_stocks=2,
            collected_stocks=2,
            expected_sectors=1,
            collected_sectors=1,
            duration_ms=1,
            coverage_pct=100.0,
            status="complete",
        ),
        started_at=0.0,
    )

    response = SectorQueryService(meta, hot).member_ranking(
        "881001",
        trade_date="2026-08-20",
        minute="09:31",
    )

    assert [item.symbol for item in response.items] == ["SZ000001", "SH600000"]


def test_sector_member_ranking_prefers_hot_store_over_live_members(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    from workbench.domain import CollectionStatus, DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
    from datetime import datetime

    def tier(delta: float, cumulative: float) -> TierPoint:
        return TierPoint(delta=delta, cumulative=cumulative, source="test", quality=DataQuality.OFFICIAL)

    trade_date = date(2026, 8, 20)
    minute = "14:30"
    batch_id = "2026-08-20T14:30"
    hot.write_complete_batch(
        [
            StockMinute(
                trade_date=trade_date,
                minute=minute,
                symbol="SH600000",
                close=10.0,
                change_pct=1.0,
                amount_delta=1000,
                funds=FundFlow(
                    main=tier(100, 900),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 14, 30),
                batch_id=batch_id,
            )
        ],
        [
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id="881001",
                change_pct=1.0,
                member_count=1,
                funds=FundFlow(
                    main=tier(100, 900),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 14, 30),
                batch_id=batch_id,
            )
        ],
        CollectionStatus(
            trade_date=trade_date,
            minute=minute,
            batch_id=batch_id,
            catalog_version="catalog-test",
            expected_stocks=1,
            collected_stocks=1,
            expected_sectors=1,
            collected_sectors=1,
            duration_ms=1,
            coverage_pct=100.0,
            status="complete",
        ),
        started_at=0.0,
    )
    live_members = [
        {"symbol": "SZ002824", "name": "和胜股份", "main_cumulative": 44_000_000.0, "change_pct": 4.5},
        {"symbol": "SH600888", "name": "新疆众和", "main_cumulative": 35_000_000.0, "change_pct": -1.2},
    ]
    response = SectorQueryService(meta, hot).member_ranking(
        "881001",
        trade_date="2026-08-20",
        minute=minute,
        live_members=live_members,
    )
    assert [item.symbol for item in response.items] == ["SH600000"]
    assert response.metadata.source != "tdx.live.members"


def test_sector_member_ranking_falls_back_to_live_members_without_hot_rows(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    live_members = [
        {"symbol": "SZ002824", "name": "和胜股份", "main_cumulative": 44_000_000.0, "change_pct": 4.5},
        {"symbol": "SH600888", "name": "新疆众和", "main_cumulative": 35_000_000.0, "change_pct": -1.2},
    ]
    response = SectorQueryService(meta, hot).member_ranking(
        "881001",
        trade_date="2026-08-20",
        minute="14:30",
        live_members=live_members,
    )
    assert [item.symbol for item in response.items] == ["SZ002824", "SH600888"]
    assert response.metadata.source == "tdx.live.members"


def test_sector_member_ranking_searches_all_catalog_members(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    from workbench.domain import CollectionStatus, DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
    from datetime import datetime

    def tier(delta: float, cumulative: float) -> TierPoint:
        return TierPoint(delta=delta, cumulative=cumulative, source="test", quality=DataQuality.OFFICIAL)

    trade_date = date(2026, 8, 20)
    minute = "09:31"
    batch_id = "2026-08-20T09:31"
    memberships = [Membership(sector_id="881001", symbol=f"SZ{index:06d}") for index in range(1, 81)]
    securities = [
        Security(symbol=f"SZ{index:06d}", code=f"{index:06d}", name=f"测试{index}", market="SZ")
        for index in range(1, 81)
    ]
    meta.replace_catalog(
        securities=securities,
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=memberships,
        version="catalog-test",
        source="test",
    )
    leader = StockMinute(
        trade_date=trade_date,
        minute=minute,
        symbol="SZ000080",
        close=10.0,
        change_pct=1.0,
        amount_delta=1000,
        funds=FundFlow(
            main=tier(100, 999),
            super=tier(0, 0),
            large=tier(0, 0),
            medium=tier(0, 0),
            small=tier(0, 0),
        ),
        observed_at=datetime(2026, 8, 20, 9, 31),
        batch_id=batch_id,
    )
    hot.write_complete_batch(
        [leader],
        [
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id="881001",
                change_pct=1.0,
                member_count=80,
                funds=FundFlow(
                    main=tier(100, 999),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            )
        ],
        CollectionStatus(
            trade_date=trade_date,
            minute=minute,
            batch_id=batch_id,
            catalog_version="catalog-test",
            expected_stocks=1,
            collected_stocks=1,
            expected_sectors=1,
            collected_sectors=1,
            duration_ms=1,
            coverage_pct=100.0,
            status="complete",
        ),
        started_at=0.0,
    )

    response = SectorQueryService(meta, hot).member_ranking(
        "881001",
        trade_date="2026-08-20",
        minute=minute,
        limit=1,
    )

    assert [item.symbol for item in response.items] == ["SZ000080"]


def test_sector_ranking_orders_by_main_cumulative(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    from workbench.domain import CollectionStatus, DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
    from datetime import datetime

    def tier(delta: float, cumulative: float) -> TierPoint:
        return TierPoint(delta=delta, cumulative=cumulative, source="test", quality=DataQuality.OFFICIAL)

    trade_date = date(2026, 8, 20)
    minute = "09:31"
    batch_id = "2026-08-20T09:31"
    stocks = [
        StockMinute(
            trade_date=trade_date,
            minute=minute,
            symbol="SH600000",
            close=10.0,
            change_pct=1.0,
            amount_delta=1000,
            funds=FundFlow(
                main=tier(100, 300),
                super=tier(0, 0),
                large=tier(0, 0),
                medium=tier(0, 0),
                small=tier(0, 0),
            ),
            observed_at=datetime(2026, 8, 20, 9, 31),
            batch_id=batch_id,
        ),
        StockMinute(
            trade_date=trade_date,
            minute=minute,
            symbol="SZ000001",
            close=12.0,
            change_pct=2.0,
            amount_delta=2000,
            funds=FundFlow(
                main=tier(200, 500),
                super=tier(0, 0),
                large=tier(0, 0),
                medium=tier(0, 0),
                small=tier(0, 0),
            ),
            observed_at=datetime(2026, 8, 20, 9, 31),
            batch_id=batch_id,
        ),
    ]
    meta.replace_catalog(
        securities=[
            Security(symbol="SH600000", code="600000", name="浦发银行", market="SH"),
            Security(symbol="SZ000001", code="000001", name="平安银行", market="SZ"),
        ],
        sectors=[
            Sector(sector_id="881001", name="银行", sector_type="industry"),
            Sector(sector_id="881002", name="证券", sector_type="industry"),
        ],
        memberships=[
            Membership(sector_id="881001", symbol="SH600000"),
            Membership(sector_id="881001", symbol="SZ000001"),
        ],
        version="catalog-test",
        source="test",
    )
    hot.write_complete_batch(
        stocks,
        [
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id="881001",
                change_pct=1.5,
                member_count=2,
                funds=FundFlow(
                    main=tier(300, 800),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            ),
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id="881002",
                change_pct=0.5,
                member_count=0,
                funds=FundFlow(
                    main=tier(100, 200),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            ),
        ],
        CollectionStatus(
            trade_date=trade_date,
            minute=minute,
            batch_id=batch_id,
            catalog_version="catalog-test",
            expected_stocks=2,
            collected_stocks=2,
            expected_sectors=2,
            collected_sectors=2,
            duration_ms=1,
            coverage_pct=100.0,
            status="complete",
        ),
        started_at=0.0,
    )

    response = SectorQueryService(meta, hot).sector_ranking(
        trade_date="2026-08-20",
        minute="09:31",
        limit=10,
    )

    assert [item.sector_id for item in response.items] == ["881001", "881002"]
    assert response.items[0].main_cumulative == 800


def test_sector_ranking_uses_latest_sector_minute_without_complete_batch(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    from workbench.domain import CollectionStatus, DataQuality, FundFlow, SectorMinute, TierPoint
    from datetime import datetime

    def tier(delta: float, cumulative: float) -> TierPoint:
        return TierPoint(delta=delta, cumulative=cumulative, source="test", quality=DataQuality.OFFICIAL)

    trade_date = date(2026, 8, 20)
    hot.write_sectors(
        [
            SectorMinute(
                trade_date=trade_date,
                minute="09:32",
                sector_id="881001",
                change_pct=1.0,
                member_count=0,
                funds=FundFlow(
                    main=tier(500, 900),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 32),
                batch_id="2026-08-20T09:32-priority",
            )
        ],
    )

    response = SectorQueryService(meta, hot).sector_ranking(trade_date="2026-08-20", limit=5)

    assert response.minute == "09:32"
    assert response.items[0].sector_id == "881001"
    assert response.items[0].main_cumulative == 900


def test_sector_fund_curve_includes_yuntu_minutes_beyond_complete(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    from workbench.domain import CollectionStatus, DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
    from datetime import datetime

    def tier(delta: float, cumulative: float) -> TierPoint:
        return TierPoint(delta=delta, cumulative=cumulative, source="test", quality=DataQuality.OFFICIAL)

    trade_date = date(2026, 8, 20)
    minute = "09:31"
    batch_id = "2026-08-20T09:31"
    hot.write_complete_batch(
        [
            StockMinute(
                trade_date=trade_date,
                minute=minute,
                symbol="SH600000",
                close=10.0,
                change_pct=1.0,
                amount_delta=1000,
                funds=FundFlow(
                    main=tier(100, 300),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            )
        ],
        [
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id="881001",
                change_pct=1.0,
                member_count=0,
                funds=FundFlow(
                    main=tier(100, 300),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            )
        ],
        CollectionStatus(
            trade_date=trade_date,
            minute=minute,
            batch_id=batch_id,
            catalog_version="catalog-test",
            expected_stocks=1,
            collected_stocks=1,
            expected_sectors=1,
            collected_sectors=1,
            duration_ms=1,
            coverage_pct=100.0,
            status="complete",
        ),
        started_at=0.0,
    )
    hot.write_sectors(
        [
            SectorMinute(
                trade_date=trade_date,
                minute="09:32",
                sector_id="881001",
                change_pct=1.2,
                member_count=0,
                funds=FundFlow(
                    main=tier(200, 500),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 32),
                batch_id="2026-08-20T09:32-yuntu",
            )
        ],
    )

    curve = hot.complete_sector_fund_curve("2026-08-20", "881001")

    assert curve.latest_complete_minute == "09:32"
    assert [row["minute"] for row in curve.rows] == ["09:31", "09:32"]
    assert curve.rows[-1]["main_cum"] == 500.0


def test_sector_snapshot_returns_hot_metrics(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)
    from workbench.domain import CollectionStatus, DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
    from datetime import datetime

    def tier(delta: float, cumulative: float) -> TierPoint:
        return TierPoint(delta=delta, cumulative=cumulative, source="test", quality=DataQuality.OFFICIAL)

    trade_date = date(2026, 8, 20)
    minute = "09:31"
    batch_id = "2026-08-20T09:31"
    hot.write_complete_batch(
        [
            StockMinute(
                trade_date=trade_date,
                minute=minute,
                symbol="SH600000",
                close=10.0,
                change_pct=1.0,
                amount_delta=1000,
                funds=FundFlow(
                    main=tier(100, 300),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            )
        ],
        [
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id="881001",
                change_pct=1.5,
                member_count=1,
                funds=FundFlow(
                    main=tier(300, 800),
                    super=tier(0, 0),
                    large=tier(0, 0),
                    medium=tier(0, 0),
                    small=tier(0, 0),
                ),
                observed_at=datetime(2026, 8, 20, 9, 31),
                batch_id=batch_id,
            )
        ],
        CollectionStatus(
            trade_date=trade_date,
            minute=minute,
            batch_id=batch_id,
            catalog_version="catalog-test",
            expected_stocks=1,
            collected_stocks=1,
            expected_sectors=1,
            collected_sectors=1,
            duration_ms=1,
            coverage_pct=100.0,
            status="complete",
        ),
        started_at=0.0,
    )

    response = SectorQueryService(meta, hot).sector_snapshot(
        ["881001"],
        trade_date="2026-08-20",
        minute=minute,
    )

    assert response.minute == minute
    assert len(response.items) == 1
    assert response.items[0].sector_id == "881001"
    assert response.items[0].main_cumulative == 800
    assert response.items[0].change_pct == 1.5


def test_sector_snapshot_omits_sectors_without_hot_rows(tmp_path: Path) -> None:
    meta, hot = seed_demo_meta_and_hot(tmp_path)

    response = SectorQueryService(meta, hot).sector_snapshot(
        ["881001", "881002"],
        trade_date="2026-08-20",
        minute="09:31",
    )

    assert response.items == []
