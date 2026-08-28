from __future__ import annotations

from datetime import date
from pathlib import Path

from workbench.collector.gap_repair import GapRepairService
from workbench.collector.retention import purge_expired_hot_databases
from workbench.collector.trading_clock import trading_minutes_for_day
from workbench.storage.hot_store import HotStore


def test_gap_repair_records_and_lists_unresolved_gaps(tmp_path: Path) -> None:
    hot = HotStore(tmp_path / "hot.sqlite")
    hot.initialize()
    service = GapRepairService(hot)
    service.record("stock", "SH600000", "2026-08-20", "09:31", "quote timeout")

    gaps = service.list_unresolved("2026-08-20")

    assert len(gaps) == 1
    assert gaps[0]["entity_id"] == "SH600000"
    assert gaps[0]["reason"] == "quote timeout"


def test_retention_purges_only_expired_hot_files(tmp_path: Path) -> None:
    hot_dir = tmp_path / "hot"
    hot_dir.mkdir()
    keep = hot_dir / "2026-08-20.sqlite"
    drop = hot_dir / "2026-07-01.sqlite"
    keep.write_text("keep", encoding="utf-8")
    drop.write_text("drop", encoding="utf-8")

    removed = purge_expired_hot_databases(tmp_path, retention_trading_days=5, today=date(2026, 8, 20))

    assert drop.name in removed
    assert keep.is_file()


def test_trading_minutes_count_matches_full_session() -> None:
    assert len(trading_minutes_for_day()) == 242
