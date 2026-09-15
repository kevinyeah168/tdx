from __future__ import annotations

from datetime import datetime, time


GRAY_FLOW_SESSION_CLOSE = time(15, 0)


def normalize_gray_flow_minute_time(minute_time: time) -> time:
    minute_time = minute_time.replace(second=0, microsecond=0)
    if minute_time > GRAY_FLOW_SESSION_CLOSE:
        return GRAY_FLOW_SESSION_CLOSE
    return minute_time


def normalize_gray_flow_sampled_at(sampled_at: datetime) -> datetime:
    normalized = normalize_gray_flow_minute_time(sampled_at.time())
    return sampled_at.replace(
        hour=normalized.hour,
        minute=normalized.minute,
        second=0,
        microsecond=0,
    )


def resolve_gray_flow_sampled_at(
    *,
    trade_date: str,
    sampled_at: datetime | None,
    provider_update_raw,
) -> datetime:
    """实时轮询显式传入 sampled_at 时用墙钟分钟；否则回退东财字段 5 更新时间。"""
    if sampled_at is not None:
        return normalize_gray_flow_sampled_at(sampled_at.replace(second=0, microsecond=0))
    update_time = str(provider_update_raw if provider_update_raw is not None else "").strip().zfill(6)
    if len(update_time) >= 4 and update_time.isdigit():
        hour = int(update_time[0:2])
        minute = int(update_time[2:4])
        second = int(update_time[4:6]) if len(update_time) >= 6 else 0
        parsed = datetime.strptime(trade_date, "%Y-%m-%d").replace(hour=hour, minute=minute, second=second)
        return normalize_gray_flow_sampled_at(parsed)
    return normalize_gray_flow_sampled_at(datetime.now().replace(second=0, microsecond=0))


def format_gray_flow_minute(sampled_at: datetime) -> str:
    return normalize_gray_flow_sampled_at(sampled_at).strftime("%H:%M")
