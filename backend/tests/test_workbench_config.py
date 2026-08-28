from __future__ import annotations

from pathlib import Path

from workbench.storage.workbench_config import (
    read_workbench_user_config,
    write_workbench_user_config,
    WorkbenchUserConfig,
    append_settings_audit,
    read_settings_audit,
)


def test_workbench_user_config_roundtrip(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    config = WorkbenchUserConfig(
        tdx_home="D:/tdx",
        collect_mode="full",
        archive_full_enabled=True,
    )
    write_workbench_user_config(data_dir, config)
    loaded = read_workbench_user_config(data_dir)
    assert loaded.tdx_home == "D:/tdx"
    assert loaded.collect_mode == "full"
    assert loaded.archive_full_enabled is True


def test_settings_audit_log(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    append_settings_audit(data_dir, "test_action", {"foo": "bar"})
    items = read_settings_audit(data_dir)
    assert len(items) == 1
    assert items[0]["action"] == "test_action"
