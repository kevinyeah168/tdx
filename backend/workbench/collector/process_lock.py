from __future__ import annotations

import atexit
import os
from pathlib import Path


def _lock_path(data_dir: Path, role: str) -> Path:
    return data_dir / "run" / f"collector-{role}.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_collector_lock(data_dir: Path, role: str) -> None:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(data_dir, role)
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw.isdigit() and _pid_alive(int(raw)):
            raise RuntimeError(f"collector-{role} already running (pid={raw})")
    path.write_text(str(os.getpid()), encoding="utf-8")

    def _release() -> None:
        if path.is_file() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink(missing_ok=True)

    atexit.register(_release)


def release_collector_lock(data_dir: Path, role: str) -> None:
    path = _lock_path(data_dir, role)
    if path.is_file() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
        path.unlink(missing_ok=True)
