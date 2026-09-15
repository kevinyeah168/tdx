from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from easy_tdx import MacClient

from workbench.collector.priority_targets import refresh_priority_stock_targets
from workbench.collector.tick_backfill_selection import (
    compute_full_day_threshold,
    select_pending_tick_backfill,
)
from workbench.collector.trading_clock import should_include_closing_minute
from workbench.config import WorkbenchSettings
from workbench.providers.tdx.stock_tick_flow import build_stock_minutes_from_tick
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class StockTickBackfillBatchResult:
    trade_date: str
    attempted: int
    backfilled: int
    skipped: int
    failed: list[str]
    minutes_written: int
    unavailable: int = 0


class _MacStockTickAdapter:
    def __init__(self, client: MacClient) -> None:
        self._client = client

    def get_tick_chart(self, *, market: int, code: str, date: int | None) -> object:
        return self._client.get_tick_chart(market=market, code=code, date=date)

    def get_stock_quotes(self, stocks: list[tuple[int, str]], fields: object = None) -> object:
        return self._client.get_stock_quotes(stocks, fields=fields)


class StockTickBackfillService:
    def __init__(self, meta: MetaStore, hot: HotStore, settings: WorkbenchSettings) -> None:
        self._meta = meta
        self._hot = hot
        self._settings = settings
        self._enhanced_client: object | None = None

    def full_day_threshold(self) -> int:
        return compute_full_day_threshold(self._settings)

    def resolve_targets(self) -> list[str]:
        return refresh_priority_stock_targets(
            self._settings,
            self._meta,
            enhanced_client=self._enhanced_client,
        )

    def bind_enhanced_client(self, client: object | None) -> None:
        self._enhanced_client = client

    def backfill_batch(
        self,
        trade_date: date,
        *,
        symbols: list[str] | None = None,
        max_symbols: int | None = None,
        force: bool = False,
    ) -> StockTickBackfillBatchResult:
        targets = symbols or self.resolve_targets()
        today = datetime.now(SHANGHAI).date()
        if max_symbols is not None:
            limit = max_symbols
        elif trade_date < today:
            limit = len(targets)
        else:
            limit = self._settings.tick_backfill_batch_size
        threshold = self.full_day_threshold()
        trade_date_str = trade_date.isoformat()

        def _stock_progress(symbol: str) -> int:
            meaningful_tick = self._hot.count_stock_tick_backfill_minutes(trade_date_str, symbol)
            if meaningful_tick:
                return meaningful_tick
            # Priority quote minutes already form the stock curve when tick momentum is empty.
            return self._hot.count_stock_minutes(trade_date_str, symbol)

        pending, skipped = select_pending_tick_backfill(
            targets,
            limit=limit,
            threshold=threshold,
            count_total_minutes=lambda symbol: self._hot.count_stock_minutes(trade_date_str, symbol),
            count_tick_minutes=_stock_progress,
            force=force,
        )

        backfilled = 0
        unavailable = 0
        failed: list[str] = []
        minutes_written = 0
        trade_date_int = int(trade_date.strftime("%Y%m%d"))

        if not pending:
            return StockTickBackfillBatchResult(
                trade_date=trade_date.isoformat(),
                attempted=0,
                backfilled=0,
                skipped=skipped,
                failed=failed,
                minutes_written=0,
                unavailable=0,
            )

        with MacClient.from_best_host() as client:
            adapter = _MacStockTickAdapter(client)
            include_closing = should_include_closing_minute(trade_date)
            for symbol in pending:
                try:
                    records = build_stock_minutes_from_tick(
                        trade_date=trade_date,
                        symbol=symbol,
                        client=adapter,
                        trade_date_int=trade_date_int,
                        include_closing_minute=include_closing,
                    )
                    if not records:
                        # Zero-momentum stock ticks are expected; do not wipe priority data.
                        unavailable += 1
                        continue
                    self._hot.delete_stock_day(trade_date.isoformat(), symbol)
                    self._hot.write_stocks(records)
                    if not include_closing:
                        self._hot.delete_stock_minutes(
                            trade_date.isoformat(),
                            symbol,
                            ("15:00",),
                        )
                    backfilled += 1
                    minutes_written += len(records)
                except Exception as exc:
                    failed.append(f"{symbol}: {exc}")

        return StockTickBackfillBatchResult(
            trade_date=trade_date.isoformat(),
            attempted=len(pending),
            backfilled=backfilled,
            skipped=skipped + unavailable,
            failed=failed,
            minutes_written=minutes_written,
            unavailable=unavailable,
        )
