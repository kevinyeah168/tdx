from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def linkage_sector_path(data_dir: Path) -> Path:
    return data_dir / "run" / "linkage_sector.json"


def _read_payload(data_dir: Path) -> dict[str, object]:
    path = linkage_sector_path(data_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_linkage_sector_id(data_dir: Path) -> str | None:
    sector_id = str(_read_payload(data_dir).get("sector_id") or "").strip()
    return sector_id or None


def read_linkage_sector_name(data_dir: Path) -> str | None:
    sector_name = str(_read_payload(data_dir).get("sector_name") or "").strip()
    return sector_name or None


def write_linkage_sector_id(
    data_dir: Path,
    sector_id: str | None,
    *,
    sector_name: str | None = None,
) -> None:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "sector_id": str(sector_id or "").strip(),
        "sector_name": str(sector_name or "").strip(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    linkage_sector_path(data_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
