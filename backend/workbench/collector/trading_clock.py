from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

TRADING_SESSIONS = (
    (time(9, 30), time(11, 30)),
    (time(13, 0), time(15, 0)),
)


def is_trading_minute(value: time) -> bool:
    for start, end in TRADING_SESSIONS:
        if start <= value <= end:
            return True
    return False


def trading_minutes_for_day() -> tuple[str, ...]:
    minutes: list[str] = []
    for start, end in TRADING_SESSIONS:
        cursor = datetime.combine(date.today(), start)
        end_at = datetime.combine(date.today(), end)
        while cursor <= end_at:
            minutes.append(cursor.strftime("%H:%M"))
            cursor += timedelta(minutes=1)
    return tuple(minutes)


def is_weekday(value: date) -> bool:
    return value.weekday() < 5


def is_trading_day(value: date) -> bool:
    return is_weekday(value)


def should_include_closing_minute(trade_date: date, now: datetime | None = None) -> bool:
    """Only append the synthetic 15:00 point after the session has ended."""
    current = now or datetime.now(SHANGHAI)
    if trade_date < current.date():
        return True
    if trade_date > current.date():
        return False
    return current.time() >= time(15, 0)


def live_session_minute_cap(trade_date: date, now: datetime | None = None) -> str | None:
    """Upper bound for minutes exposed during an in-progress trading day.

    Completed (past) sessions return ``15:00`` so historical backfills keep the
    full day including the closing point. Future dates return ``None``.
    """
    current = now or datetime.now(SHANGHAI)
    if trade_date < current.date():
        return "15:00"
    if trade_date > current.date():
        return None
    clock = current.time().replace(second=0, microsecond=0)
    if clock < time(9, 30):
        return None
    if time(11, 30) < clock < time(13, 0):
        return "11:30"
    if clock >= time(15, 0):
        return "15:00"
    if is_trading_minute(clock):
        return current.strftime("%H:%M")
    return "11:30"


def clip_minute_for_live_session(
    trade_date: date,
    minute: str | None,
    now: datetime | None = None,
) -> str | None:
    if minute is None:
        return None
    cap = live_session_minute_cap(trade_date, now)
    if cap is None:
        return None if minute == "15:00" else minute
    if minute > cap:
        return cap
    if minute == "15:00" and cap < "15:00":
        return cap
    return minute


def filter_minutes_for_live_session(
    trade_date: date,
    minutes: list[str],
    now: datetime | None = None,
) -> list[str]:
    cap = live_session_minute_cap(trade_date, now)
    if cap is None:
        return [minute for minute in minutes if minute != "15:00"]
    return [
        minute
        for minute in minutes
        if minute <= cap and not (minute == "15:00" and cap < "15:00")
    ]
