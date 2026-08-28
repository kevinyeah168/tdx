from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable


def priority_sectors_path(data_dir: Path) -> Path:
    return data_dir / "run" / "priority_sectors.json"


def read_priority_sector_ids(data_dir: Path) -> list[str]:
    path = priority_sectors_path(data_dir)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = payload.get("sector_ids")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def write_priority_sector_ids(data_dir: Path, sector_ids: Iterable[str]) -> None:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    normalized = []
    seen: set[str] = set()
    for sector_id in sector_ids:
        code = str(sector_id).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    payload = {
        "sector_ids": normalized,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    priority_sectors_path(data_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
