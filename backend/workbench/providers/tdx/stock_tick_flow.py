from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Protocol

from workbench.collector.trading_clock import (
    filter_minutes_for_live_session,
    should_include_closing_minute,
    trading_minutes_for_day,
)
from workbench.domain import DataQuality, FundFlow, StockMinute, TierPoint
from workbench.providers.tdx.classic_index_tick_flow import (
    append_closing_minute,
    change_pct,
    momentum_to_main_flow,
)
from workbench.providers.tdx.symbols import market_from_label, parse_symbol

TICK_MOMENTUM_SOURCE = "tdx.enhanced.tick_momentum"
_MARKET_INT = {"SH": 1, "SZ": 0, "BJ": 2}
# Individual stock MAC tick charts expose price/vol but momentum is typically all zeros.
_MIN_USEFUL_MOMENTUM = 1e-9


class StockTickClient(Protocol):
    def get_tick_chart(self, *, market: int, code: str, date: int | None) -> object: ...

    def get_stock_quotes(self, stocks: list[tuple[int, str]], fields: object = None) -> object: ...


def _official_main_net(row: object) -> float:
    if isinstance(row, dict):
        for key in ("main_net_amount", "main_net", "main_cum"):
            if row.get(key) is not None:
                return float(row[key])
        return 0.0
    for key in ("main_net_amount", "main_net", "main_cum"):
        value = getattr(row, key, None)
        if value is not None:
            return float(value)
    return 0.0


def _quote_row(quotes: object) -> dict[str, Any]:
    if quotes is None:
        return {}
    if hasattr(quotes, "iloc") and len(quotes):
        row = quotes.iloc[0]
        return row.to_dict() if hasattr(row, "to_dict") else dict(row)
    rows = list(quotes) if hasattr(quotes, "__iter__") and not isinstance(quotes, dict) else []
    if rows:
        first = rows[0]
        return first if isinstance(first, dict) else {}
    return {}


def tick_has_useful_momentum(tick_df: object) -> bool:
    if tick_df is None or len(tick_df) == 0:
        return False
    try:
        momentum = tick_df["momentum"].astype(float)
    except Exception:
        return False
    return bool(float(momentum.abs().max()) > _MIN_USEFUL_MOMENTUM)


def build_stock_minutes_from_tick(
    *,
    trade_date: date,
    symbol: str,
    client: StockTickClient,
    trade_date_int: int,
    include_closing_minute: bool | None = None,
) -> list[StockMinute]:
    market_label, code = parse_symbol(symbol)
    market = _MARKET_INT[market_label]
    tick = client.get_tick_chart(market=market, code=code, date=trade_date_int)
    if tick is None or len(tick) == 0:
        return []
    # Stock tick momentum is usually empty; writing zeros creates flat curves + tip cliffs.
    if not tick_has_useful_momentum(tick):
        return []

    quotes = client.get_stock_quotes([(market, code)])
    quote_payload = _quote_row(quotes)
    official_main = _official_main_net(quote_payload)
    pre_close = float(quote_payload.get("pre_close") or 0.0)
    closing_price = float(quote_payload.get("close") or quote_payload.get("price") or 0.0)

    flow = momentum_to_main_flow(tick, official_main, anchor_to_official=True)
    if include_closing_minute is None:
        include_closing_minute = should_include_closing_minute(trade_date)
    if include_closing_minute:
        flow = append_closing_minute(flow, official_main_net=official_main, closing_price=closing_price)
    by_minute = {row["minute"]: row for row in flow}
    batch_id = f"{trade_date.isoformat()}Tbackfill-tick"
    gap = DataQuality.GAP
    quality = DataQuality.CALIBRATED

    records: list[StockMinute] = []
    for minute in trading_minutes_for_day():
        point = by_minute.get(minute)
        if point is None:
            continue
        observed = datetime.combine(trade_date, time.fromisoformat(minute))
        main_cum = float(point["main_cum"])
        main_delta = float(point["main_delta"])
        price = float(point.get("price") or closing_price or 0.0)
        funds = FundFlow(
            main=TierPoint(
                delta=main_delta,
                cumulative=main_cum,
                source=TICK_MOMENTUM_SOURCE,
                quality=quality,
            ),
            super=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
            large=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
            medium=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
            small=TierPoint(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap),
        )
        records.append(
            StockMinute(
                trade_date=trade_date,
                minute=minute,
                symbol=symbol.upper(),
                close=price,
                change_pct=change_pct(price, pre_close),
                amount_delta=0.0,
                funds=funds,
                observed_at=observed,
                batch_id=batch_id,
            )
        )
    allowed = set(filter_minutes_for_live_session(trade_date, [record.minute for record in records]))
    return [record for record in records if record.minute in allowed]
