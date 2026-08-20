from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")
EXPECTED_TRADING_MINUTES = 242


def _is_weekend(day: datetime) -> bool:
    return day.weekday() >= 5


def _last_weekday(day: datetime) -> datetime:
    cursor = day
    while _is_weekend(cursor):
        cursor -= timedelta(days=1)
    return cursor


def local_now() -> datetime:
    return datetime.now(CHINA)


def resolve_trade_date(now: datetime | None = None) -> str:
    cursor = now or local_now()
    if _is_weekend(cursor):
        cursor = _last_weekday(cursor)
    return cursor.date().isoformat()


def trading_session_status(now: datetime | None = None) -> dict:
    now = now or local_now()
    trade_day = now
    if _is_weekend(trade_day):
        trade_day = _last_weekday(trade_day)

    trade_date = trade_day.date().isoformat()
    hm = now.hour * 60 + now.minute
    is_trading_day = not _is_weekend(now)

    if not is_trading_day:
        market_status = "non_trading_day"
        session_status = "closed"
    elif hm < 9 * 60 + 30:
        market_status = "pre_open"
        session_status = "closed"
    elif hm < 11 * 60 + 30:
        market_status = "open"
        session_status = "open"
    elif hm < 13 * 60:
        market_status = "lunch_break"
        session_status = "closed"
    elif hm < 15 * 60:
        market_status = "open"
        session_status = "open"
    else:
        market_status = "closed"
        session_status = "closed"

    current_minute = now.strftime("%H:%M")
    if market_status == "pre_open":
        current_minute = "09:30"

    return {
        "tradeDate": trade_date,
        "currentMinute": current_minute,
        "marketStatus": market_status,
        "sessionStatus": session_status,
        "isTradingDay": is_trading_day,
    }


def should_sample_intraday(session: dict | None = None) -> bool:
    """Sample MAC main-net during continuous trading sessions."""
    s = session or trading_session_status()
    return bool(s.get("isTradingDay")) and s.get("sessionStatus") == "open"


def resolve_intraday_view_date(
    requested: str | None,
    entity_ids: list[str],
    has_data_fn,
    latest_date_fn,
) -> str:
    """Pick default intraday view date; before open show last day with stored samples."""
    session = trading_session_status()
    if requested:
        return requested
    today = session["tradeDate"]
    if session.get("sessionStatus") == "open":
        return today
    if entity_ids:
        for eid in entity_ids:
            if has_data_fn(today, eid):
                return today
    latest = latest_date_fn(entity_ids if entity_ids else None)
    return latest or today


def public_trading_session_payload() -> dict:
    session = trading_session_status()
    messages = {
        "pre_open": "今日尚未开盘，数据在交易日 09:31 开始实时更新",
        "open": "今日交易进行中",
        "lunch_break": "午间休市，继续展示今日已产生的数据",
        "closed": "今日已收盘",
        "non_trading_day": "当前为非交易日，展示上一个交易日数据",
    }
    return {
        **session,
        "message": messages.get(session["marketStatus"], ""),
    }
