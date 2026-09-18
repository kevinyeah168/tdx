from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from workbench.collector.sector_gray_backfill import SectorGrayBackfillService
from workbench.config import WorkbenchSettings
from workbench.domain import Membership, StockGrayMinute
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore
from workbench.domain import Sector, Security


def _seed_meta(meta: MetaStore) -> None:
    meta.replace_catalog(
        securities=[
            Security(symbol="SH600000", code="600000", name="浦发银行", market="sh", active=True),
            Security(symbol="SZ000001", code="000001", name="平安银行", market="sz", active=True),
        ],
        sectors=[Sector(sector_id="881001", name="测试板块", sector_type="industry")],
        memberships=[
            Membership(sector_id="881001", symbol="SH600000"),
            Membership(sector_id="881001", symbol="SZ000001"),
        ],
        version="test-v1",
    )


def test_sector_gray_backfill_rebuilds_from_stock_gray(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path)
    settings.ensure_directories()
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    _seed_meta(meta)

    hot = HotStore(settings.hot_db_for("2026-09-11"))
    hot.initialize()
    hot.write_stock_gray(
        [
            StockGrayMinute(
                trade_date=date(2026, 9, 11),
                minute="10:30",
                symbol="SH600000",
                code="600000",
                open_cum=1.0,
                dark_cum=10.0,
                total_cum=11.0,
                observed_at=datetime(2026, 9, 11, 10, 30),
                batch_id="gray-1030",
            ),
            StockGrayMinute(
                trade_date=date(2026, 9, 11),
                minute="10:30",
                symbol="SZ000001",
                code="000001",
                open_cum=2.0,
                dark_cum=5.0,
                total_cum=7.0,
                observed_at=datetime(2026, 9, 11, 10, 30),
                batch_id="gray-1030",
            ),
            StockGrayMinute(
                trade_date=date(2026, 9, 11),
                minute="10:31",
                symbol="SH600000",
                code="600000",
                open_cum=1.5,
                dark_cum=12.0,
                total_cum=13.5,
                observed_at=datetime(2026, 9, 11, 10, 31),
                batch_id="gray-1031",
            ),
        ]
    )

    service = SectorGrayBackfillService(meta)
    result = service.backfill(hot, date(2026, 9, 11))

    assert result.stock_gray_rows == 3
    assert result.minutes == 2
    assert result.sector_rows == 2
    rows = hot.connect(readonly=True).execute(
        "SELECT minute, dark_cum, gray_covered_count FROM sector_gray_minute "
        "WHERE sector_id=? ORDER BY minute",
        ("881001",),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("10:30", 15.0, 2),
        ("10:31", 12.0, 1),
    ]
