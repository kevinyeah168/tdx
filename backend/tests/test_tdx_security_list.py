from __future__ import annotations

from pathlib import Path

from workbench.config import WorkbenchSettings
from workbench.providers.tdx.security_list import (
    load_workbench_security_cache,
    save_workbench_security_cache,
)


def test_workbench_security_cache_roundtrip(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path / "data")
    rows = [{"market": "SH", "code": "600000", "name": "浦发银行", "active": True}]
    save_workbench_security_cache(settings, rows)
    loaded = load_workbench_security_cache(settings)
    assert loaded == rows
