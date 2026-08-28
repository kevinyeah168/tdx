from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from workbench.collector.trading_clock import TRADING_SESSIONS, trading_minutes_for_day
from workbench.storage.hot_store import HotStore

CollectFn = Callable[[date, str], dict[str, object]]

BACKFILL_TIMEOUT_SECONDS = 120.0
BACKFILL_RECENT_WINDOW = 10


def _minute_le(a: str, b: str) -> bool:
    return a <= b


def expected_minutes_until(until_minute: str) -> list[str]:
    return [minute for minute in trading_minutes_for_day() if _minute_le(minute, until_minute)]


def latest_session_end_before(now_time: time) -> str | None:
    last_minute: str | None = None
    for start, end in TRADING_SESSIONS:
        if now_time >= start:
            last_minute = end.strftime("%H:%M")
    return last_minute


def _minute_subtract(minute: str, count: int) -> str:
    parsed = datetime.strptime(minute, "%H:%M")
    return (parsed - timedelta(minutes=count)).strftime("%H:%M")


class SessionBackfillService:
    """Fill missing complete minutes during lunch/after close without blocking live priority."""

    def __init__(self, hot: HotStore, collect: CollectFn) -> None:
        self._hot = hot
        self._collect = collect
        self._last_target: tuple[str, str] | None = None

    def next_missing_minute(self, trade_date: date, now: datetime) -> dict[str, object] | None:
        until = latest_session_end_before(now.time().replace(second=0, microsecond=0))
        if until is None:
            return None
        target_key = (trade_date.isoformat(), until)
        if self._last_target == target_key:
            return None

        complete = set(self._hot._complete_minutes(trade_date.isoformat()))
        recent_floor = _minute_subtract(until, BACKFILL_RECENT_WINDOW)
        missing = [
            minute
            for minute in expected_minutes_until(until)
            if minute not in complete and minute >= recent_floor
        ]
        missing.sort(reverse=True)
        if not missing:
            self._last_target = target_key
            return {"backfill": "done", "until": until, "trade_date": trade_date.isoformat()}

        minute = missing[0]
        payload: dict[str, object] = {}
        error: dict[str, object] = {}

        def run_collect() -> None:
            try:
                payload.update(self._collect(trade_date, minute))
            except Exception as exc:
                error["error"] = str(exc)

        worker = threading.Thread(target=run_collect, daemon=True)
        worker.start()
        worker.join(timeout=BACKFILL_TIMEOUT_SECONDS)
        if worker.is_alive():
            return {"mode": "backfill", "backfill": "timeout", "minute": minute, "until": until}

        if error:
            print(f"session backfill failed {minute}: {error['error']}", file=sys.stderr)
            return {"backfill": "error", "minute": minute, "error": str(error["error"])}

        result = {"mode": "backfill", "minute": minute, "until": until, **payload}
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return result
