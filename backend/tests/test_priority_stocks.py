from __future__ import annotations

from pathlib import Path

from workbench.collector.priority_stocks import (
    read_priority_manual_symbols,
    read_priority_stock_symbols,
    write_priority_stock_symbols,
    write_priority_stock_targets,
)


def test_write_and_read_priority_stock_symbols_deduplicates(tmp_path: Path) -> None:
    write_priority_stock_symbols(tmp_path, ["sh600000", "SH600000", " sz000001 "])
    assert read_priority_stock_symbols(tmp_path) == ["SH600000", "SZ000001"]
    assert read_priority_manual_symbols(tmp_path) == ["SH600000", "SZ000001"]


def test_write_priority_stock_targets_keeps_manual_and_resolved(tmp_path: Path) -> None:
    write_priority_stock_targets(tmp_path, ["SH600000"], ["SH600000", "SZ000001"])
    assert read_priority_manual_symbols(tmp_path) == ["SH600000"]
    assert read_priority_stock_symbols(tmp_path) == ["SH600000", "SZ000001"]

