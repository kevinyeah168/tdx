from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from easy_tdx import MacClient

from workbench.collector.priority_targets import refresh_priority_stock_targets
from workbench.collector.trading_clock import should_include_closing_minute, trading_minutes_for_day
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
        expected = len(trading_minutes_for_day())
        ratio = self._settings.intraday_full_minute_ratio
        return max(30, int(expected * ratio))

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
    ) -> StockTickBackfillBatchResult:
        today = datetime.now(SHANGHAI).date()
        if trade_date != today:
            return StockTickBackfillBatchResult(
                trade_date=trade_date.isoformat(),
                attempted=0,
                backfilled=0,
                skipped=0,
                failed=["tick backfill only supports current trading day"],
                minutes_written=0,
            )

        targets = symbols or self.resolve_targets()
        limit = max_symbols if max_symbols is not None else self._settings.tick_backfill_batch_size
        threshold = self.full_day_threshold()
        pending: list[str] = []
        skipped = 0
        for symbol in targets:
            existing = self._hot.count_stock_minutes(trade_date.isoformat(), symbol)
            if existing >= threshold:
                skipped += 1
                continue
            pending.append(symbol)
            if len(pending) >= limit:
                break

        backfilled = 0
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
                        failed.append(f"{symbol}: tick chart unavailable")
                        continue
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
            skipped=skipped,
            failed=failed,
            minutes_written=minutes_written,
        )
