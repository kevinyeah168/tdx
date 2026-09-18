from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain import Sector
from workbench.services.sector_groups import MAX_GROUP_MEMBERS, SectorGroupService
from workbench.storage.meta_store import MetaStore


def seed_sectors(meta: MetaStore) -> None:
    meta.replace_catalog(
        securities=[],
        sectors=[
            Sector(sector_id="881001", name="银行", sector_type="industry"),
            Sector(sector_id="880550", name="PCB概念", sector_type="concept"),
        ],
        memberships=[],
        version="test",
    )


def test_sector_group_crud(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_sectors(meta)
    service = SectorGroupService(meta)

    group = service.create_group("主线")
    assert group.name == "主线"
    assert group.sector_ids == []

    updated = service.add_members(group.id, ["881001", "880550", "881001"])
    assert updated.sector_ids == ["881001", "880550"]
    assert [item.name for item in updated.sectors] == ["银行", "PCB概念"]
    assert all(item.chart_visible for item in updated.sectors)

    service.set_active_group_id(group.id)
    assert service.read_active_group_id() == group.id
    assert service.resolve_active_group_id() == group.id

    toggled = service.set_member_chart_visible(group.id, "881001", False)
    assert toggled.sectors[0].chart_visible is False
    assert toggled.sectors[1].chart_visible is True

    renamed = service.rename_group(group.id, "观察池")
    assert renamed.name == "观察池"

    service.remove_member(group.id, "881001")
    assert service.get_group(group.id).sector_ids == ["880550"]

    service.delete_group(group.id)
    assert service.list_groups() == []
    assert service.read_active_group_id() == "all"
    assert service.resolve_active_group_id() is None


def test_sector_group_active_must_exist(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    service = SectorGroupService(meta)
    with pytest.raises(ValueError, match="group not found"):
        service.set_active_group_id("missing")


def test_sector_group_member_limit(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    service = SectorGroupService(meta)
    group = service.create_group("容量测试")
    sector_ids = [f"{880000 + index:06d}" for index in range(MAX_GROUP_MEMBERS)]
    service.add_members(group.id, sector_ids)
    with pytest.raises(ValueError, match="group member limit"):
        service.add_members(group.id, ["880999"])
