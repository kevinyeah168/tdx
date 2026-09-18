from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from workbench.collector.sector_gray_aggregator import SectorGrayAggregator
from workbench.config import WorkbenchSettings
from workbench.domain import StockGrayMinute
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


@dataclass(slots=True)
class SectorGrayBackfillResult:
    trade_date: str
    stock_gray_rows: int
    minutes: int
    sector_rows: int
    skipped: str | None = None


def list_hot_trade_dates(data_dir: Path) -> list[str]:
    hot_dir = data_dir / "hot"
    if not hot_dir.is_dir():
        return []
    dates: list[str] = []
    for path in sorted(hot_dir.glob("*.sqlite")):
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            continue
        dates.append(path.stem)
    return dates


class SectorGrayBackfillService:
    """Rebuild sector_gray_minute from existing stock_gray_minute snapshots."""

    def __init__(self, meta: MetaStore, aggregator: SectorGrayAggregator | None = None) -> None:
        memberships = meta.all_memberships()
        if not memberships:
            raise ValueError("catalog memberships empty")
        self._aggregator = aggregator or SectorGrayAggregator(memberships)

    def backfill(self, hot: HotStore, trade_date: date) -> SectorGrayBackfillResult:
        trade_date_str = trade_date.isoformat()
        hot.initialize()
        rows = hot.stock_gray_rows_for_trade_date(trade_date_str)
        if not rows:
            return SectorGrayBackfillResult(
                trade_date=trade_date_str,
                stock_gray_rows=0,
                minutes=0,
                sector_rows=0,
                skipped="no stock_gray_minute rows",
            )

        by_minute: dict[str, list[StockGrayMinute]] = defaultdict(list)
        for row in rows:
            by_minute[str(row["minute"])].append(_stock_gray_from_row(row, trade_date))

        sector_records = []
        for minute in sorted(by_minute):
            stock_records = by_minute[minute]
            observed_at = max(record.observed_at for record in stock_records)
            batch_id = stock_records[0].batch_id
            sector_records.extend(
                self._aggregator.aggregate(
                    stock_records,
                    trade_date=trade_date,
                    minute=minute,
                    observed_at=observed_at,
                    batch_id=batch_id,
                )
            )

        if sector_records:
            hot.write_sector_gray(sector_records)

        return SectorGrayBackfillResult(
            trade_date=trade_date_str,
            stock_gray_rows=len(rows),
            minutes=len(by_minute),
            sector_rows=len(sector_records),
        )


def backfill_sector_gray_for_settings(
    settings: WorkbenchSettings,
    *,
    trade_dates: list[str] | None = None,
) -> list[SectorGrayBackfillResult]:
    settings.ensure_directories()
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    service = SectorGrayBackfillService(meta)
    targets = trade_dates or list_hot_trade_dates(settings.data_dir)
    results: list[SectorGrayBackfillResult] = []
    for trade_date_str in targets:
        hot = HotStore(settings.hot_db_for(trade_date_str))
        try:
            results.append(service.backfill(hot, date.fromisoformat(trade_date_str)))
        except OSError:
            results.append(
                SectorGrayBackfillResult(
                    trade_date=trade_date_str,
                    stock_gray_rows=0,
                    minutes=0,
                    sector_rows=0,
                    skipped="hot database unavailable",
                )
            )
    return results


def _stock_gray_from_row(row: dict, trade_date: date) -> StockGrayMinute:
    observed_raw = row.get("observed_at")
    if isinstance(observed_raw, datetime):
        observed_at = observed_raw
    else:
        observed_at = datetime.fromisoformat(str(observed_raw))
    return StockGrayMinute(
        trade_date=trade_date,
        minute=str(row["minute"]),
        symbol=str(row["symbol"]).upper(),
        code=str(row["code"]),
        open_cum=float(row["open_cum"]),
        dark_cum=float(row["dark_cum"]),
        total_cum=float(row["total_cum"]),
        observed_at=observed_at,
        batch_id=str(row["batch_id"]),
        source=str(row.get("source") or "eastmoney:graymarket:darktrade"),
    )
