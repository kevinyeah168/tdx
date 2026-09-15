from workbench.collector.tick_backfill_selection import (
    compute_full_day_threshold,
    select_pending_tick_backfill,
)
from workbench.config import WorkbenchSettings


def test_select_pending_prefers_missing_tick_backfill() -> None:
    settings = WorkbenchSettings()
    threshold = compute_full_day_threshold(settings)
    totals = {
        "A": 200,
        "B": 210,
        "C": 50,
        "D": 180,
    }
    tick_counts = {
        "A": 0,
        "B": threshold,
        "C": 0,
        "D": 10,
    }

    pending, skipped = select_pending_tick_backfill(
        ["A", "B", "C", "D"],
        limit=2,
        threshold=threshold,
        count_total_minutes=lambda item: totals[item],
        count_tick_minutes=lambda item: tick_counts[item],
    )

    assert skipped == 1
    assert pending == ["C", "A"]


def test_select_pending_skips_when_tick_curve_is_full() -> None:
    settings = WorkbenchSettings()
    threshold = compute_full_day_threshold(settings)
    tick_counts = {"A": threshold, "B": threshold + 1}

    pending, skipped = select_pending_tick_backfill(
        ["A", "B"],
        limit=10,
        threshold=threshold,
        count_total_minutes=lambda _item: threshold + 5,
        count_tick_minutes=lambda item: tick_counts[item],
    )

    assert pending == []
    assert skipped == 2


def test_select_pending_rebrings_stale_tick_tip() -> None:
    settings = WorkbenchSettings()
    threshold = compute_full_day_threshold(settings)
    tips = {"A": "14:25", "B": "14:58"}

    pending, skipped = select_pending_tick_backfill(
        ["A", "B"],
        limit=10,
        threshold=threshold,
        count_total_minutes=lambda _item: threshold + 20,
        count_tick_minutes=lambda _item: threshold + 5,
        latest_tick_minute=lambda item: tips[item],
        session_minute="15:00",
        stale_gap_minutes=5,
    )

    assert pending == ["A"]
    assert skipped == 1


def test_select_pending_skips_stale_refresh_when_disabled() -> None:
    settings = WorkbenchSettings()
    threshold = compute_full_day_threshold(settings)

    pending, skipped = select_pending_tick_backfill(
        ["A"],
        limit=10,
        threshold=threshold,
        count_total_minutes=lambda _item: threshold + 20,
        count_tick_minutes=lambda _item: threshold + 5,
        latest_tick_minute=lambda _item: "14:25",
        session_minute="15:00",
        stale_gap_minutes=5,
        allow_intraday_refresh=False,
    )

    assert pending == []
    assert skipped == 1


def test_select_pending_ignores_priority_only_coverage() -> None:
    settings = WorkbenchSettings(intraday_full_minute_ratio=0.85)
    threshold = compute_full_day_threshold(settings)

    pending, skipped = select_pending_tick_backfill(
        ["880548"],
        limit=5,
        threshold=threshold,
        count_total_minutes=lambda _item: threshold + 10,
        count_tick_minutes=lambda _item: 0,
    )

    assert pending == ["880548"]
    assert skipped == 0
