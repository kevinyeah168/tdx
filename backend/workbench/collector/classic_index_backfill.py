from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from easy_tdx import MacClient

from workbench.providers.tdx.classic_index_tick_flow import (
    ClassicIndexTickClient,
    build_sector_minutes_from_tick,
)
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class ClassicIndexBackfillResult:
    trade_date: str
    requested: int
    backfilled: int
    skipped: int
    failed: list[str]
    minutes_written: int


class ClassicIndexBackfillService:
    def __init__(self, meta: MetaStore, hot: HotStore) -> None:
        self._meta = meta
        self._hot = hot

    def backfill(
        self,
        trade_date: date,
        *,
        sector_ids: list[str] | None = None,
        min_existing_minutes: int = 10,
        overwrite: bool = False,
    ) -> ClassicIndexBackfillResult:
        targets = self._resolve_targets(sector_ids)
        backfilled = 0
        skipped = 0
        failed: list[str] = []
        minutes_written = 0
        trade_date_int = int(trade_date.strftime("%Y%m%d"))

        with MacClient.from_best_host() as client:
            for sector_id in targets:
                existing = self._hot.count_sector_minutes(trade_date.isoformat(), sector_id)
                if existing >= min_existing_minutes and not overwrite:
                    skipped += 1
                    continue
                try:
                    records = build_sector_minutes_from_tick(
                        trade_date=trade_date,
                        sector_id=sector_id,
                        member_count=0,
                        client=_MacTickAdapter(client),
                        trade_date_int=trade_date_int,
                    )
                    if not records:
                        failed.append(f"{sector_id}: tick chart unavailable")
                        continue
                    self._hot.write_sectors(records)
                    backfilled += 1
                    minutes_written += len(records)
                except Exception as exc:
                    failed.append(f"{sector_id}: {exc}")

        return ClassicIndexBackfillResult(
            trade_date=trade_date.isoformat(),
            requested=len(targets),
            backfilled=backfilled,
            skipped=skipped,
            failed=failed,
            minutes_written=minutes_written,
        )

    def _resolve_targets(self, sector_ids: list[str] | None) -> list[str]:
        if sector_ids:
            return sorted({sector_id.strip() for sector_id in sector_ids if sector_id.strip()})
        with self._meta.connect() as connection:
            rows = connection.execute(
                "SELECT sector_id FROM sector_master WHERE sector_type='classic_index' ORDER BY sector_id"
            ).fetchall()
        return [str(row[0]) for row in rows]


class _MacTickAdapter:
    def __init__(self, client: MacClient) -> None:
        self._client = client

    def get_tick_chart(self, *, market: int, code: str, date: int | None) -> object:
        return self._client.get_tick_chart(market=market, code=code, date=date)

    def get_board_summary(self, board_symbol: str) -> object:
        return self._client.get_board_summary(board_symbol)

    def get_stock_quotes(self, stocks: list[tuple[int, str]], fields: object = None) -> object:
        return self._client.get_stock_quotes(stocks, fields=fields)
