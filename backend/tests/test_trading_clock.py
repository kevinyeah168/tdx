from __future__ import annotations

from datetime import date, datetime, time
from typing import Callable

import pytest

from workbench.collector.trading_clock import (
    filter_minutes_for_live_session,
    is_trading_day,
    is_trading_minute,
    live_session_minute_cap,
    trading_minutes_for_day,
)


def test_trading_minutes_cover_both_sessions() -> None:
    minutes = trading_minutes_for_day()

    assert minutes[0] == "09:30"
    assert "11:30" in minutes
    assert "13:00" in minutes
    assert minutes[-1] == "15:00"
    assert len(minutes) == 242


def test_trading_minute_boundaries() -> None:
    assert is_trading_minute(time(9, 30))
    assert is_trading_minute(time(11, 30))
    assert not is_trading_minute(time(11, 31))
    assert is_trading_minute(time(13, 0))
    assert is_trading_day(date(2026, 8, 20))
    assert not is_trading_day(date(2026, 8, 22))


def test_filter_minutes_excludes_closing_point_during_live_session() -> None:
    trade_date = date(2026, 8, 27)
    now = datetime(2026, 8, 27, 9, 50)

    assert live_session_minute_cap(trade_date, now) == "09:50"
    assert filter_minutes_for_live_session(
        trade_date,
        ["09:30", "09:50", "15:00"],
        now,
    ) == ["09:30", "09:50"]


def test_past_session_keeps_full_day_including_close() -> None:
    trade_date = date(2026, 8, 31)
    now = datetime(2026, 9, 1, 10, 0)

    assert live_session_minute_cap(trade_date, now) == "15:00"
    assert filter_minutes_for_live_session(
        trade_date,
        ["09:30", "14:59", "15:00"],
        now,
    ) == ["09:30", "14:59", "15:00"]
