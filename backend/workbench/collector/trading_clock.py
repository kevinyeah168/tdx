from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

TRADING_SESSIONS = (
    (time(9, 30), time(11, 30)),
    (time(13, 0), time(15, 0)),
)

AUCTION_START = time(9, 15)
AUCTION_END = time(9, 25)
POST_AUCTION_END = time(9, 30)

AUCTION_BOARD_SORT_KEYS = ("ratio", "amount", "change", "volume", "price")
AUCTION_BOARD_DEFAULT_SORT = "ratio"
AUCTION_BOARD_SORT_PARAMS: dict[str, str] = {
    "ratio": "f10",
    "amount": "f63",
    "change": "f3",
    "volume": "f5",
    "price": "f2",
}


def is_trading_minute(value: time) -> bool:
    for start, end in TRADING_SESSIONS:
        if start <= value <= end:
            return True
    return False


def is_pre_market_auction_minute(value: time) -> bool:
    return AUCTION_START <= value < POST_AUCTION_END


def is_gray_collect_minute(value: time) -> bool:
    return is_trading_minute(value) or is_pre_market_auction_minute(value)


def auction_phase_at(now: datetime | None = None) -> str:
    """Return waiting | auction | post_auction | closed for Shanghai wall clock."""
    current = now or datetime.now(SHANGHAI)
    if not is_trading_day(current.date()):
        return "closed"
    clock = current.time().replace(second=0, microsecond=0)
    if clock < AUCTION_START:
        return "waiting"
    if AUCTION_START <= clock < AUCTION_END:
        return "auction"
    if AUCTION_END <= clock < POST_AUCTION_END:
        return "post_auction"
    return "closed"


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
