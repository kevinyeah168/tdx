from __future__ import annotations

from pathlib import Path

from workbench.domain import Security
from workbench.services.custom_sector_directory_sync import (
    CustomSectorDirectorySyncService,
    parse_stock_codes_from_text,
    sector_name_from_filename,
)
from workbench.services.custom_sectors import CustomSectorService
from workbench.storage.meta_store import MetaStore


def seed_stocks(meta: MetaStore) -> None:
    meta.replace_catalog(
        securities=[
            Security(symbol="SH600630", code="600630", name="龙头股份", market="SH", active=True),
            Security(symbol="SZ001365", code="001365", name="测试股", market="SZ", active=True),
            Security(symbol="SH600000", code="600000", name="浦发银行", market="SH", active=True),
        ],
        sectors=[],
        memberships=[],
        version="test",
    )


def test_parse_stock_codes_from_text() -> None:
    assert parse_stock_codes_from_text("600630\n001365, 600000") == ["600630", "001365", "600000"]
    assert parse_stock_codes_from_text("重复 600630\n600630") == ["600630"]


def test_sector_name_from_filename() -> None:
    assert sector_name_from_filename("哨兵仓.csv") == "哨兵仓"
    assert sector_name_from_filename("zt.txt") == "zt"


def test_directory_sync_upserts_and_replaces_members(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_stocks(meta)

    directory = tmp_path / "tdx-export"
    directory.mkdir()
    (directory / "哨兵仓.csv").write_text("600630\n001365\n", encoding="utf-8")
    (directory / "zt.txt").write_text("600000\n", encoding="utf-8")

    service = CustomSectorDirectorySyncService(meta)
    first = service.sync_directory(directory)
    assert first.files_seen == 2
    assert first.sectors_updated == 2
    assert first.members_total == 3

    sector_service = CustomSectorService(meta)
    sentinel = sector_service.find_sector_by_name("哨兵仓")
    assert sentinel is not None
    assert sentinel.symbols == ["SH600630", "SZ001365"]
    assert sentinel.source_type == "directory"

    (directory / "哨兵仓.csv").write_text("600000\n", encoding="utf-8")
    second = service.sync_directory(directory)
    updated = sector_service.find_sector_by_name("哨兵仓")
    assert updated is not None
    assert updated.symbols == ["SH600000"]
    assert second.sectors_updated == 2


def test_directory_sync_deletes_sector_when_file_removed(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_stocks(meta)

    directory = tmp_path / "tdx-export"
    directory.mkdir()
    (directory / "哨兵仓.csv").write_text("600630\n", encoding="utf-8")
    (directory / "zt.txt").write_text("600000\n", encoding="utf-8")

    service = CustomSectorDirectorySyncService(meta)
    sector_service = CustomSectorService(meta)

    first = service.sync_directory(directory, previous_managed_names=[])
    assert set(first.managed_sector_names) == {"哨兵仓", "zt"}
    assert sector_service.find_sector_by_name("zt") is not None

    (directory / "zt.txt").unlink()
    second = service.sync_directory(directory, previous_managed_names=first.managed_sector_names)
    assert second.sectors_deleted == 1
    assert sector_service.find_sector_by_name("zt") is None
    assert sector_service.find_sector_by_name("哨兵仓") is not None
    assert second.managed_sector_names == ["哨兵仓"]


def test_set_members_replaces_existing(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_stocks(meta)
    service = CustomSectorService(meta)
    sector = service.create_sector("观察池")
    service.add_members(sector.sector_id, ["SH600630", "SZ001365"])
    replaced = service.set_members(sector.sector_id, ["SH600000"])
    assert replaced.symbols == ["SH600000"]
