from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from workbench.collector.yuntu_snapshot_collector import YuntuSnapshotCollector
from workbench.config import WorkbenchSettings
from workbench.domain import Membership, Sector, Security
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def _seed_catalog(meta: MetaStore) -> None:
    meta.replace_catalog(
        securities=[
            Security(symbol="SH600519", code="600519", name="Moutai", market="SH"),
            Security(symbol="SZ000001", code="000001", name="PAB", market="SZ"),
        ],
        sectors=[
            Sector(sector_id="880656", name="CPO", sector_type="concept"),
        ],
        memberships=[
            Membership(sector_id="880656", symbol="SH600519"),
        ],
        version="test-v1",
    )


def test_yuntu_collector_writes_successful_snapshot(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    _seed_catalog(meta)
    hot = HotStore(tmp_path / "hot.sqlite")
    hot.initialize()
    settings = WorkbenchSettings(data_dir=tmp_path)
    collector = YuntuSnapshotCollector(meta, hot, settings=settings)
    script = (
        'var G_REAL_HQ = ["'
        + __import__("base64").b64encode(
            __import__("workbench.providers.tdx.yuntu_sector_flow", fromlist=["encode_gg_list_from_items"]).encode_gg_list_from_items(
                [
                    {"stockcode": "600519", "f_amo_sum_wan": 100.0, "dqzf": 0.01, "now": 10.0},
                    {"stockcode": "000001", "f_amo_sum_wan": 20.0, "dqzf": 0.02, "now": 11.0},
                    {"stockcode": "880656", "f_amo_sum_wan": -50.0, "dqzf": -0.01, "now": 0.0},
                    {"stockcode": "880001", "f_amo_sum_wan": 900.0, "dqzf": 0.008, "now": 0.0},
                    {"stockcode": "880011", "f_amo_sum_wan": 400.0, "dqzf": 0.005, "now": 0.0},
                    {"stockcode": "880041", "f_amo_sum_wan": 300.0, "dqzf": 0.02, "now": 0.0},
                    {"stockcode": "880031", "f_amo_sum_wan": 150.0, "dqzf": 0.015, "now": 0.0},
                ]
            )
        ).decode("ascii")
        + '"];'
    )
    with patch(
        "workbench.collector.yuntu_snapshot_collector.fetch_real_hq_script",
        return_value=script,
    ):
        result = collector.collect(date(2026, 9, 14), "09:31")
    assert result["yuntu_stocks"] == 2
    assert result["yuntu_sectors"] == 1
    with hot.connect(readonly=True) as connection:
        stock = connection.execute(
            "SELECT main_cum, tier_meta_json FROM stock_minute WHERE symbol=? AND minute=?",
            ("SH600519", "09:31"),
        ).fetchone()
        sector = connection.execute(
            "SELECT main_cum FROM sector_minute WHERE sector_id=? AND minute=?",
            ("880656", "09:31"),
        ).fetchone()
    assert stock is not None
    assert stock[0] == 1_000_000.0
    assert "official" in stock[1]
    assert sector is not None
    market_rows = connection.execute(
        "SELECT scope, main_cum FROM market_scope_minute WHERE minute=? ORDER BY scope",
        ("09:31",),
    ).fetchall()
    by_scope = {str(row[0]): float(row[1]) for row in market_rows}
    assert len(by_scope) == 5
    assert by_scope["cy"] == 1_500_000.0
    assert by_scope["sz"] == 200_000.0


def test_yuntu_collector_writes_gap_minute_when_poll_fails(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    _seed_catalog(meta)
    hot = HotStore(tmp_path / "hot.sqlite")
    hot.initialize()
    settings = WorkbenchSettings(data_dir=tmp_path)
    collector = YuntuSnapshotCollector(meta, hot, settings=settings)
    with patch(
        "workbench.collector.yuntu_snapshot_collector.fetch_real_hq_script",
        side_effect=RuntimeError("network down"),
    ):
        collector.collect(date(2026, 9, 14), "09:31")
    collector.collect(date(2026, 9, 14), "09:32")
    with hot.connect(readonly=True) as connection:
        row = connection.execute(
            "SELECT tier_meta_json, batch_id FROM stock_minute WHERE symbol=? AND minute=?",
            ("SH600519", "09:31"),
        ).fetchone()
    assert row is not None
    assert "yuntu-gap" in row[1]
    assert "gap" in row[0]


def test_yuntu_collector_does_not_gap_successful_minute(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    _seed_catalog(meta)
    hot = HotStore(tmp_path / "hot.sqlite")
    hot.initialize()
    settings = WorkbenchSettings(data_dir=tmp_path)
    collector = YuntuSnapshotCollector(meta, hot, settings=settings)
    script = (
        'var G_REAL_HQ = ["'
        + __import__("base64").b64encode(
            __import__("workbench.providers.tdx.yuntu_sector_flow", fromlist=["encode_gg_list_from_items"]).encode_gg_list_from_items(
                [{"stockcode": "600519", "f_amo_sum_wan": 1.0, "dqzf": 0.0, "now": 1.0}]
            )
        ).decode("ascii")
        + '"];'
    )
    with patch(
        "workbench.collector.yuntu_snapshot_collector.fetch_real_hq_script",
        return_value=script,
    ):
        collector.collect(date(2026, 9, 14), "09:31")
    collector.collect(date(2026, 9, 14), "09:32")
    with hot.connect(readonly=True) as connection:
        row = connection.execute(
            "SELECT tier_meta_json, batch_id FROM stock_minute WHERE symbol=? AND minute=?",
            ("SH600519", "09:31"),
        ).fetchone()
    assert row is not None
    assert "yuntu-gap" not in row[1]
    assert '"main":{"source":"tdx.yuntu.real_hq","quality":"official"}' in row[0]
