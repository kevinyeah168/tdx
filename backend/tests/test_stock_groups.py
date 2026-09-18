from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain import Security
from workbench.services.stock_groups import MAX_GROUP_MEMBERS, StockGroupService
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


def test_stock_group_crud(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_stocks(meta)
    service = StockGroupService(meta)

    group = service.create_group("自选")
    assert group.name == "自选"
    assert group.symbol_ids == []

    updated = service.add_members(group.id, ["SH600000", "sz000001", "SH600000"])
    assert updated.symbol_ids == ["SH600000", "SZ000001"]
    assert [item.name for item in updated.symbols] == ["浦发银行", "平安银行"]

    service.set_active_group_id(group.id)
    assert service.read_active_group_id() == group.id

    renamed = service.rename_group(group.id, "观察池")
    assert renamed.name == "观察池"

    service.remove_member(group.id, "SH600000")
    assert service.get_group(group.id).symbol_ids == ["SZ000001"]

    service.delete_group(group.id)
    assert service.list_groups() == []
    assert service.read_active_group_id() == "all"


def test_stock_group_active_must_exist(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    service = StockGroupService(meta)
    with pytest.raises(ValueError, match="group not found"):
        service.set_active_group_id("missing")


def test_stock_group_member_limit(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    service = StockGroupService(meta)
    group = service.create_group("容量测试")
    symbols = [f"SH{600000 + index:06d}" for index in range(MAX_GROUP_MEMBERS)]
    service.add_members(group.id, symbols)
    with pytest.raises(ValueError, match="group member limit"):
        service.add_members(group.id, ["SH699999"])
