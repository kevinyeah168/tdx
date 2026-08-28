from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from workbench.config import WorkbenchSettings

HEARTBEAT_STALE_AFTER = timedelta(minutes=2)
ROLE_FILES = {
    "hot": "collector-hot.json",
    "archive": "collector-archive.json",
}


def write_collector_heartbeat(data_dir: Path, role: str = "collector") -> None:
    run_dir = data_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    payload = {
        "last_seen": now,
        "role": role,
    }
    if role in ROLE_FILES:
        (run_dir / ROLE_FILES[role]).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        (run_dir / "collector.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return

    status = read_collector_status(data_dir)
    aggregate = {
        "last_seen": status.get("last_seen"),
        "roles": status.get("roles", {}),
        "online": status.get("online", False),
    }
    (run_dir / "collector.json").write_text(
        json.dumps(aggregate, ensure_ascii=False),
        encoding="utf-8",
    )


def read_collector_status(
    data_dir: Path,
    *,
    max_age: timedelta = HEARTBEAT_STALE_AFTER,
) -> dict[str, object]:
    run_dir = data_dir / "run"
    now = datetime.now()
    roles: dict[str, object] = {}
    latest_seen: datetime | None = None
    latest_raw: str | None = None
    any_online = False

    for role, filename in ROLE_FILES.items():
        path = run_dir / filename
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        last_seen = payload.get("last_seen")
        if not last_seen:
            continue
        seen_at = datetime.fromisoformat(str(last_seen))
        online = now - seen_at <= max_age
        roles[role] = {"online": online, "last_seen": str(last_seen)}
        if online:
            any_online = True
        if latest_seen is None or seen_at > latest_seen:
            latest_seen = seen_at
            latest_raw = str(last_seen)

    legacy_path = run_dir / "collector.json"
    if legacy_path.is_file() and not any_online:
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload.get("roles"), dict) and payload.get("last_seen"):
            aggregate_online = bool(payload.get("online"))
            if aggregate_online:
                any_online = True
                latest_raw = str(payload.get("last_seen"))
            for role, info in payload["roles"].items():
                if role not in roles and isinstance(info, dict):
                    roles[role] = info
        elif payload.get("last_seen") and "roles" not in payload:
            seen_at = datetime.fromisoformat(str(payload["last_seen"]))
            online = now - seen_at <= max_age
            roles["collector"] = {"online": online, "last_seen": str(payload["last_seen"])}
            if online:
                any_online = True
                latest_raw = str(payload["last_seen"])

    return {
        "online": any_online,
        "last_seen": latest_raw,
        "roles": roles,
    }


def seed_demo_history(settings: WorkbenchSettings) -> None:
    if settings.data_dir.name != "workbench-demo":
        return
    from workbench.storage.history_store import HistoryStore
    from workbench.providers.tdx.bars import normalize_bar_row

    fixture_path = (
        Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "tdx" / "bars.json"
    )
    if not fixture_path.is_file():
        return
    rows = json.loads(fixture_path.read_text(encoding="utf-8"))
    history_path = settings.data_dir / "history" / "bars.sqlite"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history = HistoryStore(history_path)
    history.initialize()
    for symbol in ("SH600000", "SZ000001", "BJ920001"):
        bars = [normalize_bar_row(row, symbol=symbol, period="day") for row in rows]
        history.replace_bars(symbol=symbol, period="day", bars=bars, source="fixture")
