from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Protocol

from workbench.collector.trading_clock import (
    filter_minutes_for_live_session,
    should_include_closing_minute,
    trading_minutes_for_day,
)
from workbench.domain import DataQuality, FundFlow, SectorMinute, TierPoint

TICK_MOMENTUM_SOURCE = "tdx.enhanced.tick_momentum"
# Cap single-minute momentum outliers before cumsum; keeps shape but kills cliffs.
_MOMENTUM_DELTA_CLIP_Z = 6.0


def fmt_minute(value: object) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value)
    return text[:5] if len(text) >= 5 else text


def change_pct(price: float, pre_close: float) -> float:
    if not pre_close:
        return 0.0
    return round((price - pre_close) / pre_close * 100, 2)


def clip_momentum_deltas(deltas: object, *, z: float = _MOMENTUM_DELTA_CLIP_Z) -> object:
    """Winsorize raw tick momentum deltas with a median/MAD fence."""
    values = deltas.astype(float)
    if len(values) < 8:
        return values
    median = float(values.median())
    mad = float((values - median).abs().median())
    if mad <= 1e-12:
        abs_med = float(values.abs().median())
        if abs_med <= 1e-12:
            return values
        mad = abs_med
    fence = z * 1.4826 * mad
    return values.clip(median - fence, median + fence)


def momentum_to_main_flow(
    tick_df: object,
    official_main_net: float,
    *,
    anchor_to_official: bool = True,
) -> list[dict[str, Any]]:
    """Convert board index tick momentum into scaled main-force minute curve.

    Shape follows tick ``momentum`` (outlier-clipped); magnitude is anchored to
    the official ``main_net_amount`` (same unit as priority/明盘) so tick backfill
    and live quote minutes stay on one scale. Closing minute is carried forward
    from 14:59 and is not forced to a separate summary override.
    """
    if tick_df is None or len(tick_df) == 0:
        return []

    clipped = clip_momentum_deltas(tick_df["momentum"])
    cum_raw = clipped.cumsum()
    last_raw = float(cum_raw.iloc[-1]) if len(cum_raw) else 0.0
    if anchor_to_official and official_main_net and abs(last_raw) > 1e-9:
        scale = float(official_main_net) / last_raw
    elif abs(last_raw) > 1e-9:
        # Fallback only when official main is unavailable.
        scale = 1e8
    else:
        scale = 0.0

    flow: list[dict[str, Any]] = []
    prev = 0.0
    for index in range(len(tick_df)):
        row = tick_df.iloc[index]
        cum_v = float(cum_raw.iloc[index]) * scale
        flow.append(
            {
                "minute": fmt_minute(row["time"]),
                "main_delta": cum_v - prev,
                "main_cum": cum_v,
                "price": float(row.get("price") or 0.0),
            }
        )
        prev = cum_v
    return flow


def append_closing_minute(
    flow: list[dict[str, Any]],
    *,
    official_main_net: float,
    closing_price: float,
) -> list[dict[str, Any]]:
    if not flow:
        return flow
    last = flow[-1]
    prev_cum = float(last["main_cum"])
    if last["minute"] == "15:00":
        last["price"] = closing_price or last.get("price", 0.0)
        return flow
    return [
        *flow,
        {
            "minute": "15:00",
            "main_delta": 0.0,
            "main_cum": prev_cum,
            "price": closing_price or float(last.get("price") or 0.0),
        },
    ]


class ClassicIndexTickClient(Protocol):
    def get_tick_chart(self, *, market: int, code: str, date: int | None) -> object: ...

    def get_board_summary(self, board_symbol: str) -> object: ...

    def get_stock_quotes(self, stocks: list[tuple[int, str]], fields: object = None) -> object: ...


def _quote_fields(row: object) -> tuple[float, float, float]:
    if isinstance(row, dict):
        pre_close = float(row.get("pre_close") or 0.0)
        close = float(row.get("close") or row.get("price") or 0.0)
        return close, pre_close, pre_close
    pre_close = float(getattr(row, "pre_close", 0.0) or 0.0)
    close = float(getattr(row, "close", None) or getattr(row, "price", 0.0) or 0.0)
    return close, pre_close, pre_close


def build_sector_minutes_from_tick(
    *,
    trade_date: date,
    sector_id: str,
    member_count: int,
    client: ClassicIndexTickClient,
    trade_date_int: int,
    include_closing_minute: bool | None = None,
) -> list[SectorMinute]:
    tick = client.get_tick_chart(market=1, code=sector_id, date=trade_date_int)
    if tick is None or len(tick) == 0:
        return []

    summary = client.get_board_summary(sector_id)
    if isinstance(summary, dict):
        official_main = float(summary.get("main_net_amount") or 0.0)
        members = int(summary.get("member_count") or member_count)
    else:
        official_main = float(getattr(summary, "main_net_amount", 0.0) or 0.0)
        members = int(getattr(summary, "member_count", 0) or member_count)

    quotes = client.get_stock_quotes([(1, sector_id)])
    if hasattr(quotes, "iloc") and len(quotes):
        quote_row = quotes.iloc[0]
        quote_payload = quote_row.to_dict() if hasattr(quote_row, "to_dict") else quote_row
    else:
        quote_payload = {}
    _close, pre_close, _ = _quote_fields(quote_payload)

    flow = momentum_to_main_flow(tick, official_main, anchor_to_official=True)
    closing_price = _close
    if include_closing_minute is None:
        include_closing_minute = should_include_closing_minute(trade_date)
    if include_closing_minute:
        flow = append_closing_minute(
            flow,
            official_main_net=official_main,
            closing_price=closing_price,
        )

    by_minute = {row["minute"]: row for row in flow}
    batch_id = f"{trade_date.isoformat()}Tbackfill-tick"
    gap = DataQuality.GAP
    quality = DataQuality.CALIBRATED

    records: list[SectorMinute] = []
    for minute in trading_minutes_for_day():
        point = by_minute.get(minute)
        if point is None:
            continue
        observed = datetime.combine(trade_date, time.fromisoformat(minute))
        funds = FundFlow(
            main=TierPoint(
                delta=float(point["main_delta"]),
                cumulative=float(point["main_cum"]),
                source=TICK_MOMENTUM_SOURCE,
                quality=quality,
            ),
            super=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
            large=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
            medium=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
            small=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
        )
        records.append(
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id=sector_id,
                change_pct=change_pct(float(point.get("price") or 0.0), pre_close),
                member_count=members,
                funds=funds,
                observed_at=observed,
                batch_id=batch_id,
            )
        )
    allowed = set(filter_minutes_for_live_session(trade_date, [record.minute for record in records]))
    return [record for record in records if record.minute in allowed]
