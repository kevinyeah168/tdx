from __future__ import annotations

from datetime import date
from pathlib import Path

from workbench.collector.retention import purge_expired_hot_databases


def test_retention_rejects_invalid_window(tmp_path: Path) -> None:
    try:
        purge_expired_hot_databases(tmp_path, retention_trading_days=0, today=date(2026, 8, 20))
    except ValueError as error:
        assert "at least 1" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_retention_noop_when_hot_dir_missing(tmp_path: Path) -> None:
    assert purge_expired_hot_databases(tmp_path, retention_trading_days=30, today=date(2026, 8, 20)) == []
