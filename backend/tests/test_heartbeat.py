from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from workbench.collector.heartbeat import read_collector_status, write_collector_heartbeat


def test_read_collector_status_uses_hot_and_archive(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True)

    stale = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
    fresh = datetime.now().isoformat(timespec="seconds")

    (run_dir / "collector.json").write_text(
        f'{{"last_seen": "{stale}", "role": "collector"}}',
        encoding="utf-8",
    )
    (run_dir / "collector-hot.json").write_text(
        f'{{"last_seen": "{fresh}", "role": "hot"}}',
        encoding="utf-8",
    )
    (run_dir / "collector-archive.json").write_text(
        f'{{"last_seen": "{fresh}", "role": "archive"}}',
        encoding="utf-8",
    )

    status = read_collector_status(data_dir)
    assert status["online"] is True
    assert status["roles"]["hot"]["online"] is True
    assert status["roles"]["archive"]["online"] is True


def test_write_collector_heartbeat_updates_aggregate(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    write_collector_heartbeat(data_dir, role="hot")
    write_collector_heartbeat(data_dir, role="archive")

    status = read_collector_status(data_dir)
    assert status["online"] is True
    aggregate = (data_dir / "run" / "collector.json").read_text(encoding="utf-8")
    assert "roles" in aggregate
    assert "hot" in aggregate
