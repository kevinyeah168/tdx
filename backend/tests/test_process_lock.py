from __future__ import annotations

import os
from pathlib import Path

import pytest

from workbench.collector.process_lock import acquire_collector_lock, release_collector_lock


def test_collector_lock_prevents_duplicate(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    acquire_collector_lock(data_dir, "hot")
    try:
        with pytest.raises(RuntimeError, match="already running"):
            acquire_collector_lock(data_dir, "hot")
    finally:
        release_collector_lock(data_dir, "hot")
    acquire_collector_lock(data_dir, "hot")
    release_collector_lock(data_dir, "hot")


def test_collector_lock_allows_different_roles(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    acquire_collector_lock(data_dir, "hot")
    acquire_collector_lock(data_dir, "archive")
    release_collector_lock(data_dir, "hot")
    release_collector_lock(data_dir, "archive")
