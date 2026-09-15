from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from easy_tdx import MacClient

from workbench.collector.priority_collector import PrioritySectorCollector
from workbench.collector.tick_backfill_selection import (
    compute_full_day_threshold,
    select_pending_tick_backfill,
)
from workbench.collector.trading_clock import should_include_closing_minute
from workbench.config import WorkbenchSettings
from workbench.providers.tdx.classic_index_tick_flow import build_sector_minutes_from_tick
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class TickBackfillBatchResult:
    trade_date: str
    attempted: int
    backfilled: int
    skipped: int
    failed: list[str]
    minutes_written: int


class _MacTickAdapter:
    def __init__(self, client: MacClient) -> None:
        self._client = client

    def get_tick_chart(self, *, market: int, code: str, date: int | None) -> object:
        return self._client.get_tick_chart(market=market, code=code, date=date)

    def get_board_summary(self, board_symbol: str) -> object:
        return self._client.get_board_summary(board_symbol)

    def get_stock_quotes(self, stocks: list[tuple[int, str]], fields: object = None) -> object:
        return self._client.get_stock_quotes(stocks, fields=fields)


class SectorTickBackfillService:
    """Rebuild full-day sector intraday curves from MAC tick momentum + official main."""

    def __init__(
        self,
        provider: object,
        meta: MetaStore,
        hot: HotStore,
        settings: WorkbenchSettings,
        *,
        data_dir,
        rank_pool: int,
        max_sectors: int,
    ) -> None:
        self._provider = provider
        self._meta = meta
        self._hot = hot
        self._settings = settings
        self._data_dir = data_dir
        self._priority_sectors = PrioritySectorCollector(
            provider,
            meta,
            hot,
            data_dir=data_dir,
            rank_pool=rank_pool,
            max_sectors=max_sectors,
        )

    def full_day_threshold(self) -> int:
        return compute_full_day_threshold(self._settings)

    def resolve_targets(self, trade_date: date, minute: str) -> list[str]:
        return self._priority_sectors._resolve_sector_ids_for_minute(trade_date, minute)

    def backfill_batch(
        self,
        trade_date: date,
        *,
        sector_ids: list[str] | None = None,
        minute: str | None = None,
        max_sectors: int | None = None,
        force: bool = False,
    ) -> TickBackfillBatchResult:
        effective_minute = minute or datetime.now(SHANGHAI).strftime("%H:%M")
        targets = sector_ids or self.resolve_targets(trade_date, effective_minute)
        # Historical days: fill the full target set in one pass (no live batching).
        today = datetime.now(SHANGHAI).date()
        if max_sectors is not None:
            limit = max_sectors
        elif trade_date < today:
            limit = len(targets)
        else:
            limit = self._settings.tick_backfill_batch_size
        threshold = self.full_day_threshold()
        trade_date_str = trade_date.isoformat()
        live_session = trade_date >= today
        pending, skipped = select_pending_tick_backfill(
            targets,
            limit=limit,
            threshold=threshold,
            count_total_minutes=lambda sector_id: self._hot.count_sector_minutes(
                trade_date_str, sector_id
            ),
            count_tick_minutes=lambda sector_id: self._hot.count_sector_tick_backfill_minutes(
                trade_date_str, sector_id
            ),
            force=force,
            latest_tick_minute=lambda sector_id: self._hot.latest_sector_tick_backfill_minute(
                trade_date_str, sector_id
            ),
            session_minute=effective_minute,
            allow_intraday_refresh=not live_session,
        )
        if live_session and not force:
            # Live concept boards: MAC tick is shaped once per day; priority board_summary
            # owns the moving tip. Re-pulling tick rescales the whole curve and causes
            # multi-billion jumps (e.g. CPO -15亿 vs -47亿 within minutes).
            pending = [
                sector_id
                for sector_id in pending
                if self._hot.count_sector_tick_backfill_minutes(trade_date_str, sector_id) == 0
            ]

        backfilled = 0
        failed: list[str] = []
        minutes_written = 0
        trade_date_int = int(trade_date.strftime("%Y%m%d"))

        if not pending:
            return TickBackfillBatchResult(
                trade_date=trade_date.isoformat(),
                attempted=0,
                backfilled=0,
                skipped=skipped,
                failed=failed,
                minutes_written=0,
            )

        with MacClient.from_best_host() as client:
            adapter = _MacTickAdapter(client)
            include_closing = should_include_closing_minute(trade_date)
            for sector_id in pending:
                try:
                    records = build_sector_minutes_from_tick(
                        trade_date=trade_date,
                        sector_id=sector_id,
                        member_count=0,
                        client=adapter,
                        trade_date_int=trade_date_int,
                        include_closing_minute=include_closing,
                    )
                    if not records:
                        failed.append(f"{sector_id}: tick chart unavailable")
                        continue
                    # Historical days: replace the whole curve. Live session: keep priority
                    # board_summary minutes and only refresh tick-backfill rows.
                    if trade_date < today:
                        self._hot.delete_sector_day(trade_date.isoformat(), sector_id)
                    else:
                        self._hot.delete_sector_tick_backfill(
                            trade_date.isoformat(),
                            sector_id,
                        )
                    self._hot.write_sectors(records)
                    if not include_closing:
                        self._hot.delete_sector_minutes(
                            trade_date.isoformat(),
                            sector_id,
                            ("15:00",),
                        )
                    backfilled += 1
                    minutes_written += len(records)
                except Exception as exc:
                    failed.append(f"{sector_id}: {exc}")

        return TickBackfillBatchResult(
            trade_date=trade_date.isoformat(),
            attempted=len(pending),
            backfilled=backfilled,
            skipped=skipped,
            failed=failed,
            minutes_written=minutes_written,
        )
