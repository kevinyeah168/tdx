from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain import Security
from workbench.services.custom_sectors import (
    MAX_CUSTOM_SECTOR_MEMBERS,
    CustomSectorService,
)
from workbench.storage.meta_store import MetaStore


def seed_stocks(meta: MetaStore) -> None:
    meta.replace_catalog(
        securities=[
            Security(symbol="SH600000", code="600000", name="浦发银行", market="SH", active=True),
            Security(symbol="SZ000001", code="000001", name="平安银行", market="SZ", active=True),
        ],
        sectors=[],
        memberships=[],
        version="test",
    )


def test_custom_sector_crud(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_stocks(meta)
    service = CustomSectorService(meta)

    sector = service.create_sector("观察池")
    assert sector.name == "观察池"
    assert sector.sector_id.startswith("custom_")
    assert sector.source_type == "manual"
    assert sector.symbols == []

    updated = service.add_members(sector.sector_id, ["SH600000", "sz000001", "SH600000"])
    assert updated.symbols == ["SH600000", "SZ000001"]
    assert [item.name for item in updated.members] == ["浦发银行", "平安银行"]

    renamed = service.rename_sector(sector.sector_id, "核心自选")
    assert renamed.name == "核心自选"

    service.remove_member(sector.sector_id, "SH600000")
    assert service.get_sector(sector.sector_id).symbols == ["SZ000001"]

    service.delete_sector(sector.sector_id)
    assert service.list_sectors() == []


def test_custom_sector_member_limit(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    service = CustomSectorService(meta)
    sector = service.create_sector("容量测试")
    symbols = [f"SH{600000 + index:06d}" for index in range(MAX_CUSTOM_SECTOR_MEMBERS)]
    service.add_members(sector.sector_id, symbols)
    with pytest.raises(ValueError, match="member limit"):
        service.add_members(sector.sector_id, ["SH699999"])
