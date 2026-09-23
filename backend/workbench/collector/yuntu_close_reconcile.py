"""Re-fetch yuntu real_hq after the session closes to align final minute with cloud map."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from workbench.collector.session_backfill import latest_session_end_before

CollectFn = Callable[[date, str], dict[str, object]]

CLOSE_MINUTE = "15:00"
MAX_PASSES = 2
SECOND_PASS_DELAY = timedelta(minutes=2)


class YuntuCloseReconcileService:
    """Overwrite the closing minute with fresh yuntu snapshots once or twice after 15:00."""

    def __init__(self, collect: CollectFn) -> None:
        self._collect = collect
        self._passes_done: dict[str, int] = {}
        self._first_pass_at: dict[str, datetime] = {}

    def reconcile_if_due(self, trade_date: date, now: datetime) -> dict[str, object] | None:
        until = latest_session_end_before(now.time().replace(second=0, microsecond=0))
        if until != CLOSE_MINUTE:
            return None

        key = trade_date.isoformat()
        passes = self._passes_done.get(key, 0)
        if passes >= MAX_PASSES:
            return None

        if passes == 1:
            first_at = self._first_pass_at.get(key)
            if first_at is not None and now - first_at < SECOND_PASS_DELAY:
                return None

        payload = self._collect(trade_date, CLOSE_MINUTE)
        if passes == 0:
            self._first_pass_at[key] = now
        self._passes_done[key] = passes + 1
        return {
            "mode": "yuntu-close-reconcile",
            "pass": passes + 1,
            "minute": CLOSE_MINUTE,
            **payload,
        }
