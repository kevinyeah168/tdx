from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from workbench.collector.process_lock import release_collector_lock
from workbench.storage.workbench_config import read_workbench_user_config


def _lock_pid(data_dir: Path, role: str) -> int | None:
    path = data_dir / "run" / f"collector-{role}.lock"
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_process_tree(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def stop_collector_role(data_dir: Path, role: str) -> bool:
    pid = _lock_pid(data_dir, role)
    stopped = False
    if pid is not None and _pid_alive(pid):
        stopped = _kill_process_tree(pid)
    release_collector_lock(data_dir, role)
    lock_path = data_dir / "run" / f"collector-{role}.lock"
    if lock_path.is_file():
        lock_path.unlink(missing_ok=True)
    return stopped or pid is None


def start_collector_role(
    *,
    backend_dir: Path,
    data_dir: Path,
    role: str,
    tdx_home: Path,
    log_dir: Path,
) -> dict[str, object]:
    python_exe = backend_dir / ".venv" / "Scripts" / "python.exe"
    if not python_exe.is_file():
        python_exe = Path(sys.executable)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"collector-{role}-restart.log"
    args = [
        str(python_exe),
        "-u",
        "-m",
        "workbench.collector.main",
        "--real",
        "--serve",
        "--mode",
        role,
        "--data-dir",
        str(data_dir),
        "--tdx-home",
        str(tdx_home),
    ]
    with log_path.open("a", encoding="utf-8") as log_handle:
        log_handle.write(f"\n--- restart {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    proc = subprocess.Popen(
        args,
        cwd=str(backend_dir),
        stdout=open(log_path, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return {"role": role, "pid": proc.pid, "log": str(log_path)}


def restart_collectors(settings_data_dir: Path, backend_dir: Path | None = None) -> dict[str, object]:
    data_dir = settings_data_dir.resolve()
    user_cfg = read_workbench_user_config(data_dir)
    tdx_home = Path(user_cfg.tdx_home)
    if backend_dir is None:
        backend_dir = Path(__file__).resolve().parents[2]
    log_dir = data_dir.parent / "run" / "workbench"
    if not log_dir.is_dir():
        log_dir = data_dir / "run"

    results: dict[str, object] = {"stopped": [], "started": []}
    for role in ("hot", "archive"):
        if stop_collector_role(data_dir, role):
            results["stopped"].append(role)
        time.sleep(0.3)

    for role in ("hot", "archive"):
        started = start_collector_role(
            backend_dir=backend_dir,
            data_dir=data_dir,
            role=role,
            tdx_home=tdx_home,
            log_dir=log_dir,
        )
        results["started"].append(started)

    return results
