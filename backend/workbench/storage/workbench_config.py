from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CollectMode = Literal["selective", "full"]


class WorkbenchUserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tdx_home: str = "C:/new_tdx64"
    collect_mode: CollectMode = "selective"
    archive_full_enabled: bool = False

    @field_validator("tdx_home")
    @classmethod
    def _strip_tdx_home(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("tdx_home must not be blank")
        return cleaned


def workbench_config_path(data_dir: Path) -> Path:
    return data_dir / "run" / "workbench_config.json"


def settings_audit_path(data_dir: Path) -> Path:
    return data_dir / "run" / "settings_audit.jsonl"


def read_workbench_user_config(data_dir: Path) -> WorkbenchUserConfig:
    path = workbench_config_path(data_dir)
    if not path.is_file():
        return WorkbenchUserConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return WorkbenchUserConfig()
    try:
        return WorkbenchUserConfig.model_validate(payload)
    except ValueError:
        return WorkbenchUserConfig()


def write_workbench_user_config(data_dir: Path, config: WorkbenchUserConfig) -> WorkbenchUserConfig:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    workbench_config_path(data_dir).write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config


def append_settings_audit(data_dir: Path, action: str, detail: dict[str, object]) -> None:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        **detail,
    }
    with settings_audit_path(data_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_settings_audit(data_dir: Path, limit: int = 20) -> list[dict[str, object]]:
    path = settings_audit_path(data_dir)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    items: list[dict[str, object]] = []
    for line in reversed(lines[-limit:]):
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items
