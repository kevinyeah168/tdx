from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from workbench.collector.scheduler import MinuteScheduler


class _StopLoop(Exception):
    pass


def test_scheduler_runs_priority_only_during_trading_when_priority_enabled() -> None:
    full_calls: list[tuple[date, str]] = []
    priority_calls: list[tuple[date, str]] = []
    sleep_calls: list[float] = []

    def collect(trade_date: date, minute: str) -> dict[str, object]:
        full_calls.append((trade_date, minute))
        return {"collected_stocks": 100}

    def priority_collect(trade_date: date, minute: str) -> dict[str, object]:
        priority_calls.append((trade_date, minute))
        return {"priority_sectors": 12}

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 4:
            raise _StopLoop

    fixed_now = datetime(2026, 8, 25, 10, 15, 0)
    scheduler = MinuteScheduler(
        collect=collect,
        priority_collect=priority_collect,
        sleep=sleep,
        priority_interval_seconds=5.0,
        full_collect_interval_seconds=45.0,
        mode="hot",
    )

    with (
        patch("workbench.collector.scheduler.is_trading_day", return_value=True),
        patch("workbench.collector.scheduler.is_trading_minute", return_value=True),
        patch("workbench.collector.scheduler.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = fixed_now
        with pytest.raises(_StopLoop):
            scheduler.serve()

    assert full_calls == []
    assert len(priority_calls) == 4
    assert all(4.9 <= value <= 5.0 for value in sleep_calls)


def test_scheduler_runs_gray_every_15_seconds() -> None:
    priority_calls: list[tuple[date, str]] = []
    gray_calls: list[tuple[date, str]] = []
    sleep_calls: list[float] = []
    clock = [
        datetime(2026, 8, 25, 10, 15, 0),
        datetime(2026, 8, 25, 10, 15, 5),
        datetime(2026, 8, 25, 10, 15, 10),
        datetime(2026, 8, 25, 10, 15, 16),
    ]
    timestamps = [1000.0, 1005.0, 1010.0, 1016.0]

    def priority_collect(trade_date: date, minute: str) -> dict[str, object]:
        priority_calls.append((trade_date, minute))
        return {"priority_sectors": 1}

    def gray_collect(trade_date: date, minute: str) -> dict[str, object]:
        gray_calls.append((trade_date, minute))
        return {"gray_stocks": 5000}

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 4:
            raise _StopLoop

    scheduler = MinuteScheduler(
        collect=lambda *_args, **_kwargs: {},
        priority_collect=priority_collect,
        gray_collect=gray_collect,
        sleep=sleep,
        priority_interval_seconds=5.0,
        gray_interval_seconds=15.0,
        mode="hot",
    )

    with (
        patch("workbench.collector.scheduler.is_trading_day", return_value=True),
        patch("workbench.collector.scheduler.is_trading_minute", return_value=True),
        patch("workbench.collector.scheduler.time.time", side_effect=timestamps),
        patch("workbench.collector.scheduler.datetime") as mock_datetime,
    ):
        mock_datetime.now.side_effect = clock
        with pytest.raises(_StopLoop):
            scheduler.serve()

    assert len(priority_calls) == 4
    assert gray_calls == [
        (date(2026, 8, 25), "10:15"),
        (date(2026, 8, 25), "10:15"),
    ]


def test_scheduler_archive_skips_trading_minutes() -> None:
    priority_calls: list[tuple[date, str]] = []
    backfill_calls: list[tuple[date, datetime]] = []
    sleep_calls: list[float] = []

    def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 3:
            raise _StopLoop

    fixed_now = datetime(2026, 8, 25, 10, 15, 0)
    scheduler = MinuteScheduler(
        collect=lambda *_args, **_kwargs: {"collected_stocks": 100},
        priority_collect=lambda trade_date, minute: priority_calls.append((trade_date, minute)) or {},
        session_backfill=lambda trade_date, now: backfill_calls.append((trade_date, now)) or {},
        sleep=sleep,
        mode="archive",
        priority_interval_seconds=5.0,
    )

    with (
        patch("workbench.collector.scheduler.is_trading_day", return_value=True),
        patch("workbench.collector.scheduler.is_trading_minute", return_value=True),
        patch("workbench.collector.scheduler.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = fixed_now
        with pytest.raises(_StopLoop):
            scheduler.serve()

    assert priority_calls == []
    assert backfill_calls == []
    assert all(value == 5.0 for value in sleep_calls)


def test_scheduler_runs_session_backfill_outside_trading_minutes() -> None:
    backfill_calls: list[tuple[date, datetime]] = []

    def backfill(trade_date: date, now: datetime) -> dict[str, object]:
        backfill_calls.append((trade_date, now))
        return {"backfill": "done"}

    def sleep(seconds: float) -> None:
        if len(backfill_calls) >= 2:
            raise _StopLoop

    fixed_now = datetime(2026, 8, 25, 11, 48, 0)
    scheduler = MinuteScheduler(
        collect=lambda *_args, **_kwargs: {},
        priority_collect=lambda *_args, **_kwargs: {"priority_sectors": 0},
        session_backfill=backfill,
        sleep=sleep,
    )

    with (
        patch("workbench.collector.scheduler.is_trading_day", return_value=True),
        patch("workbench.collector.scheduler.is_trading_minute", return_value=False),
        patch("workbench.collector.scheduler.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = fixed_now
        with pytest.raises(_StopLoop):
            scheduler.serve()

    assert len(backfill_calls) == 2
