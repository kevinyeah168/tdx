from __future__ import annotations

from pathlib import Path

from workbench.collector.priority_sectors import read_priority_sector_ids
from workbench.collector.priority_stocks import read_priority_stock_symbols
from workbench.collector.priority_targets import (
    apply_hot_target_sync,
    merge_priority_sector_ids,
    resolve_priority_stock_symbols,
    sector_member_symbols,
)
from workbench.config import WorkbenchSettings
from workbench.services.custom_sectors import CustomSectorService
from workbench.storage.meta_store import MetaStore


def test_merge_priority_sector_ids_prefers_linkage_and_dedupes() -> None:
    merged = merge_priority_sector_ids(
        selected=["881001", "881002"],
        ranked=["881003", "881001"],
        linkage_sector_id="881071",
        max_sectors=4,
    )
    assert merged == ["881071", "881001", "881002", "881003"]


def test_resolve_priority_stock_symbols_expands_sector_members(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = WorkbenchSettings(
        data_dir=data_dir,
        priority_max_sectors=10,
        priority_max_stocks=20,
        priority_sector_members=2,
        priority_linkage_members=1,
    )
    settings.ensure_directories()
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    with meta.connect() as connection:
        connection.executemany(
            "INSERT INTO security_master(symbol, code, name, market, active) VALUES(?, ?, ?, ?, 1)",
            [
                ("SH600000", "600000", "浦发银行", "SH"),
                ("SZ000001", "000001", "平安银行", "SZ"),
                ("SH600362", "600362", "江西铜业", "SH"),
            ],
        )
        connection.executemany(
            "INSERT INTO sector_master(sector_id, name, sector_type) VALUES(?, ?, ?)",
            [("881071", "工业金属", "industry"), ("881001", "电力", "industry")],
        )
        connection.executemany(
            "INSERT INTO sector_membership(sector_id, symbol) VALUES(?, ?)",
            [
                ("881071", "SH600362"),
                ("881071", "SH600000"),
                ("881001", "SZ000001"),
                ("881001", "SH600000"),
            ],
        )
        connection.commit()

    merged = resolve_priority_stock_symbols(
        meta,
        settings,
        sector_ids=["881071", "881001"],
        linkage_sector_id="881071",
        manual_symbols=["SH600000"],
        enhanced_client=None,
    )
    assert merged == ["SH600000", "SH600362", "SZ000001"]


def test_sector_member_symbols_reads_custom_sector_catalog(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    with meta.connect() as connection:
        connection.executemany(
            "INSERT INTO security_master(symbol, code, name, market, active) VALUES(?, ?, ?, ?, 1)",
            [("SH600000", "600000", "浦发银行", "SH")],
        )
        connection.commit()
    service = CustomSectorService(meta)
    sector = service.create_sector("哨兵仓")
    service.add_members(sector.sector_id, ["SH600000"])

    class _BrokenLiveClient:
        def get_board_members(self, *_args, **_kwargs):
            raise RuntimeError("live members should not be called for custom sectors")

    symbols = sector_member_symbols(
        meta,
        sector.sector_id,
        per_sector_limit=10,
        enhanced_client=_BrokenLiveClient(),
        sector_name="哨兵仓",
    )
    assert symbols == ["SH600000"]


def test_apply_hot_target_sync_writes_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = WorkbenchSettings(
        data_dir=data_dir,
        priority_max_sectors=10,
        priority_max_stocks=10,
        priority_sector_members=5,
        priority_linkage_members=5,
    )
    settings.ensure_directories()
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    with meta.connect() as connection:
        connection.executemany(
            "INSERT INTO security_master(symbol, code, name, market, active) VALUES(?, ?, ?, ?, 1)",
            [("SH600000", "600000", "浦发银行", "SH")],
        )
        connection.executemany(
            "INSERT INTO sector_master(sector_id, name, sector_type) VALUES(?, ?, ?)",
            [("881071", "工业金属", "industry")],
        )
        connection.executemany(
            "INSERT INTO sector_membership(sector_id, symbol) VALUES(?, ?)",
            [("881071", "SH600000")],
        )
        connection.commit()

    result = apply_hot_target_sync(
        settings,
        meta,
        selected_sector_ids=["881001"],
        rank_sector_ids=["881002", "881003"],
        selected_stock_symbols=["SH600000"],
        linkage_sector_id="881071",
        linkage_sector_name="工业金属",
    )
    assert result["sectors"] >= 3
    assert "881071" in read_priority_sector_ids(data_dir)
    assert "SH600000" in read_priority_stock_symbols(data_dir)
