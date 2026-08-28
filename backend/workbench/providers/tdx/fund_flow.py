from __future__ import annotations

from datetime import date, datetime

from workbench.domain import DataQuality, FundFlow, ProviderMinuteBatch, StockMinute, TierPoint
from workbench.providers.tdx.quotes import TdxQuoteService, normalize_quote_batch, _row_value, _symbol_from_row
from workbench.providers.tdx.transactions import (
    ALGORITHM_VERSION,
    ESTIMATED_SOURCE,
    TierTotals,
    aggregate_tier_deltas,
    dedupe_transactions,
    estimated_quality,
)


def _tier_point(
    *,
    delta: float,
    cumulative: float,
    source: str,
    quality: DataQuality,
) -> TierPoint:
    return TierPoint(delta=delta, cumulative=cumulative, source=source, quality=quality)


def _main_from_row(row: object) -> float:
    if isinstance(row, dict):
        for key in ("main_net_amount", "main_net", "main_cum"):
            if key in row and row[key] is not None:
                return float(row[key])
        return 0.0
    for key in ("main_net_amount", "main_net", "main_cum"):
        if hasattr(row, key):
            value = getattr(row, key)
            if value is not None:
                return float(value)
    return 0.0


def build_stock_minutes(
    *,
    trade_date: date,
    minute: str,
    quote_rows: list[object],
    previous_main_cum: dict[str, float] | None = None,
    previous_amount_cum: dict[str, float] | None = None,
    observed_at: datetime | None = None,
    batch_id: str | None = None,
) -> list[StockMinute]:
    observed = observed_at or datetime.combine(trade_date, datetime.strptime(minute, "%H:%M").time())
    batch = batch_id or f"{trade_date.isoformat()}T{minute}"
    prev_main = previous_main_cum or {}
    prev_amount = previous_amount_cum or {}
    snapshots = normalize_quote_batch(
        quote_rows,
        trade_date=trade_date,
        minute=minute,
        observed_at=observed,
        source="tdx.enhanced.quotes",
        quality=DataQuality.OFFICIAL,
    )
    row_by_symbol = {_symbol_from_row(row): row for row in quote_rows}
    stocks: list[StockMinute] = []
    for snapshot in snapshots:
        row = row_by_symbol.get(snapshot.symbol, snapshot.model_dump(mode="json"))
        main_cum = _main_from_row(row)
        main_delta = main_cum - prev_main.get(snapshot.symbol, 0.0)
        amount_delta = max(snapshot.amount - prev_amount.get(snapshot.symbol, 0.0), 0.0)
        gap_quality = DataQuality.GAP
        funds = FundFlow(
            main=_tier_point(
                delta=main_delta,
                cumulative=main_cum,
                source="tdx.enhanced.main_net_amount",
                quality=DataQuality.OFFICIAL,
            ),
            super=_tier_point(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap_quality),
            large=_tier_point(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap_quality),
            medium=_tier_point(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap_quality),
            small=_tier_point(delta=0.0, cumulative=0.0, source="tdx.unavailable", quality=gap_quality),
        )
        stocks.append(
            StockMinute(
                trade_date=trade_date,
                minute=minute,
                symbol=snapshot.symbol,
                close=snapshot.price,
                change_pct=snapshot.change_pct,
                amount_delta=amount_delta,
                funds=funds,
                observed_at=observed,
                batch_id=batch,
            )
        )
    return stocks


def build_minute_batch_from_quotes(
    *,
    trade_date: date,
    minute: str,
    quote_service: TdxQuoteService,
    symbols: list[str],
    expected_stocks: int,
    previous_main_cum: dict[str, float] | None = None,
    previous_amount_cum: dict[str, float] | None = None,
    observed_at: datetime | None = None,
) -> ProviderMinuteBatch:
    observed = observed_at or datetime.combine(trade_date, datetime.strptime(minute, "%H:%M").time())
    batch_id = f"{trade_date.isoformat()}T{minute}"
    quote_rows = quote_service.fetch_quote_rows(symbols)
    stocks = build_stock_minutes(
        trade_date=trade_date,
        minute=minute,
        quote_rows=quote_rows,
        previous_main_cum=previous_main_cum,
        previous_amount_cum=previous_amount_cum,
        observed_at=observed,
        batch_id=batch_id,
    )
    if previous_main_cum is not None:
        for stock in stocks:
            previous_main_cum[stock.symbol] = stock.funds.main.cumulative
    if previous_amount_cum is not None:
        for stock in stocks:
            previous_amount_cum[stock.symbol] = (
                previous_amount_cum.get(stock.symbol, 0.0) + stock.amount_delta
            )
    return ProviderMinuteBatch(
        trade_date=trade_date,
        minute=minute,
        stocks=stocks,
        expected_stocks=expected_stocks,
    )


def apply_estimated_tiers(
    stocks: list[StockMinute],
    transactions_by_symbol: dict[str, list[object]],
    *,
    previous_tier_cum: dict[str, dict[str, float]] | None = None,
) -> list[StockMinute]:
    prev = previous_tier_cum or {}
    enriched: list[StockMinute] = []
    quality = estimated_quality()
    for stock in stocks:
        rows = dedupe_transactions(transactions_by_symbol.get(stock.symbol, []))
        totals = aggregate_tier_deltas(rows)
        previous = prev.get(stock.symbol, {})
        super_cum = previous.get("super", 0.0) + totals.super_delta
        large_cum = previous.get("large", 0.0) + totals.large_delta
        medium_cum = previous.get("medium", 0.0) + totals.medium_delta
        small_cum = previous.get("small", 0.0) + totals.small_delta
        funds = FundFlow(
            main=stock.funds.main,
            super=_tier_point(
                delta=totals.super_delta,
                cumulative=super_cum,
                source=ESTIMATED_SOURCE,
                quality=quality,
            ),
            large=_tier_point(
                delta=totals.large_delta,
                cumulative=large_cum,
                source=ESTIMATED_SOURCE,
                quality=quality,
            ),
            medium=_tier_point(
                delta=totals.medium_delta,
                cumulative=medium_cum,
                source=ESTIMATED_SOURCE,
                quality=quality,
            ),
            small=_tier_point(
                delta=totals.small_delta,
                cumulative=small_cum,
                source=ESTIMATED_SOURCE,
                quality=quality,
            ),
        )
        enriched.append(stock.model_copy(update={"funds": funds}))
    return enriched


def algorithm_version() -> str:
    return ALGORITHM_VERSION
