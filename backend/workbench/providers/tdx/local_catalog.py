from __future__ import annotations

from pathlib import Path
from typing import Any


def _tnf_path(tdx_home: Path, market: str) -> Path | None:
    filename = {"SH": "shs.tnf", "SZ": "szs.tnf", "BJ": "bjs.tnf"}.get(market.upper())
    if filename is None:
        return None
    candidates = (
        tdx_home / "T0002" / "hq_cache" / filename,
        tdx_home / "hq_cache" / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def read_tnf_names(tdx_home: Path, market: str) -> dict[str, str]:
    path = _tnf_path(tdx_home, market)
    if path is None:
        return {}

    names: dict[str, str] = {}
    raw = path.read_bytes()
    record_size = 314
    for offset in range(0, len(raw) - record_size + 1, record_size):
        chunk = raw[offset : offset + record_size]
        code = chunk[0:6].decode("gbk", errors="ignore").strip()
        if len(code) != 6 or not code.isdigit():
            continue
        name = chunk[31:47].decode("gbk", errors="ignore").strip()
        if name:
            names[code] = name
    return names


def load_local_security_rows(tdx_home: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for market in ("SH", "SZ", "BJ"):
        names = read_tnf_names(tdx_home, market)
        for code, name in names.items():
            rows.append({"market": market, "code": code, "name": name})
    return rows
