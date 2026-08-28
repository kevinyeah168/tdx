from __future__ import annotations

from pathlib import Path

from workbench.collector.priority_sectors import (
    read_priority_sector_ids,
    write_priority_sector_ids,
)


def test_write_and_read_priority_sector_ids_deduplicates(tmp_path: Path) -> None:
    write_priority_sector_ids(tmp_path, ["881001", "881001", " 881002 ", ""])
    assert read_priority_sector_ids(tmp_path) == ["881001", "881002"]


def test_read_priority_sector_ids_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_priority_sector_ids(tmp_path) == []


def test_read_priority_sector_ids_invalid_json_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "run"
    path.mkdir(parents=True)
    (path / "priority_sectors.json").write_text("{bad", encoding="utf-8")
    assert read_priority_sector_ids(tmp_path) == []
