from __future__ import annotations

from collections.abc import Callable

from workbench.collector.trading_clock import trading_minutes_for_day
from workbench.config import WorkbenchSettings

# Re-queue tick backfill when the tick tip lags the live session by this many minutes.
_TICK_STALE_GAP_MINUTES = 5


def compute_full_day_threshold(settings: WorkbenchSettings) -> int:
    expected = len(trading_minutes_for_day())
    ratio = settings.intraday_full_minute_ratio
    return max(30, int(expected * ratio))


def _session_minute_gap(earlier: str | None, later: str | None) -> int:
    if not earlier or not later:
        return 0
    minutes = trading_minutes_for_day()
    try:
        start = minutes.index(earlier)
        end = minutes.index(later)
    except ValueError:
        return 0
    return max(0, end - start)


def select_pending_tick_backfill(
    targets: list[str],
    *,
    limit: int,
    threshold: int,
    count_total_minutes: Callable[[str], int],
    count_tick_minutes: Callable[[str], int],
    force: bool = False,
    latest_tick_minute: Callable[[str], str | None] | None = None,
    session_minute: str | None = None,
    stale_gap_minutes: int = _TICK_STALE_GAP_MINUTES,
    allow_intraday_refresh: bool = True,
) -> tuple[list[str], int]:
    """Pick targets that still need MAC tick curves.

    Priority quote rows can accumulate enough minute coverage to look complete while
    never receiving a tick backfill batch. Only tick-backfill minute counts count
    toward completion; total minute count is used as a tie-breaker.

    Additionally, a sector whose tick tip lags ``session_minute`` by more than
    ``stale_gap_minutes`` is treated as pending even when the tick count already
    crossed the full-day threshold (afternoon refresh).
    """
    if limit <= 0 or not targets:
        return [], 0

    candidates: list[tuple[str, int, int]] = []
    skipped = 0
    for target_id in targets:
        tick_minutes = count_tick_minutes(target_id)
        stale = False
        if (
            allow_intraday_refresh
            and not force
            and latest_tick_minute is not None
            and session_minute
            and tick_minutes > 0
        ):
            tip = latest_tick_minute(target_id)
            stale = _session_minute_gap(tip, session_minute) >= stale_gap_minutes
        if not force and tick_minutes >= threshold and not stale:
            skipped += 1
            continue
        total_minutes = count_total_minutes(target_id)
        candidates.append((target_id, tick_minutes, total_minutes))

    candidates.sort(key=lambda item: (item[1], item[2], item[0]))
    pending = [item[0] for item in candidates[:limit]]
    return pending, skipped
