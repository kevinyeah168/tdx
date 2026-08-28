from __future__ import annotations

import socket
from pathlib import Path

from easy_tdx.config import get_port
from easy_tdx.transport.sync import MAC_HOSTS

from workbench.providers.tdx.local_catalog import read_tnf_names


def probe_tdx_home(tdx_home: Path) -> dict[str, object]:
    home = Path(tdx_home)
    vipdoc = home / "vipdoc"
    vipdoc_ok = vipdoc.is_dir()
    tnf_ok = any(
        read_tnf_names(home, market)
        for market in ("SH", "SZ", "BJ")
    )
    mac_port = int(get_port())
    mac_reachable = _probe_mac_port(mac_port)
    sample_day = _find_sample_day_file(vipdoc) if vipdoc_ok else None
    return {
        "tdx_home": str(home),
        "vipdoc_ok": vipdoc_ok,
        "tnf_ok": tnf_ok,
        "mac_port": mac_port,
        "mac_reachable": mac_reachable,
        "client_likely_running": mac_reachable,
        "sample_day_file": sample_day,
        "ok": vipdoc_ok and (tnf_ok or sample_day is not None),
    }


def _probe_mac_port(port: int, timeout: float = 1.5) -> bool:
    hosts = [host for host in MAC_HOSTS if host and host not in {"0.0.0.0"}]
    if not hosts:
        hosts = ["127.0.0.1"]
    for host in hosts:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _find_sample_day_file(vipdoc: Path) -> str | None:
    for market in ("sh", "sz"):
        lday = vipdoc / market / "lday"
        if not lday.is_dir():
            continue
        for path in sorted(lday.glob("*.day"))[:1]:
            return str(path.relative_to(vipdoc.parent))
    return None
