from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable


def priority_stocks_path(data_dir: Path) -> Path:
    return data_dir / "run" / "priority_stocks.json"


def _read_payload(data_dir: Path) -> dict[str, object]:
    path = priority_stocks_path(data_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_priority_manual_symbols(data_dir: Path) -> list[str]:
    payload = _read_payload(data_dir)
    manual = payload.get("manual_symbols")
    if isinstance(manual, list):
        return [str(item).strip().upper() for item in manual if str(item).strip()]
    # Backward compatibility: treat legacy resolved list as manual picks.
    legacy = payload.get("symbols")
    if isinstance(legacy, list):
        return [str(item).strip().upper() for item in legacy if str(item).strip()]
    return []


def read_priority_stock_symbols(data_dir: Path) -> list[str]:
    payload = _read_payload(data_dir)
    raw = payload.get("symbols")
    if not isinstance(raw, list):
        return []
    return [str(item).strip().upper() for item in raw if str(item).strip()]


def write_priority_stock_targets(
    data_dir: Path,
    manual_symbols: Iterable[str],
    resolved_symbols: Iterable[str],
) -> None:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    def normalize(items: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for symbol in items:
            code = str(symbol).strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        return normalized

    payload = {
        "manual_symbols": normalize(manual_symbols),
        "symbols": normalize(resolved_symbols),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    priority_stocks_path(data_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_priority_stock_symbols(data_dir: Path, symbols: Iterable[str]) -> None:
    write_priority_stock_targets(data_dir, symbols, symbols)
