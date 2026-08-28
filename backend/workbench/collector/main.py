from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Sequence

from workbench.collector.priority_collector import PrioritySectorCollector
from workbench.collector.priority_stock_collector import PriorityStockCollector
from workbench.collector.classic_index_backfill import ClassicIndexBackfillService
from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.heartbeat import write_collector_heartbeat
from workbench.collector.history_sync import HistorySyncService, refresh_security_cache
from workbench.collector.minute_collector import MinuteCollector
from workbench.collector.process_lock import acquire_collector_lock, release_collector_lock
from workbench.collector.retention import purge_expired_hot_databases
from workbench.collector.scheduler import CollectFn, MinuteScheduler
from workbench.collector.session_backfill import SessionBackfillService
from workbench.collector.sector_tick_backfill import SectorTickBackfillService
from workbench.collector.stock_tick_backfill import StockTickBackfillService
from workbench.config import WorkbenchSettings, merge_user_config
from workbench.providers.fake import FakeMarketProvider
from workbench.providers.tdx.provider import TdxMarketProvider
from workbench.providers.tdx.runtime import create_real_provider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore
from workbench.storage.workbench_config import read_workbench_user_config


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("stocks must be an integer") from error
    if str(parsed) != value or parsed < 1:
        raise argparse.ArgumentTypeError("stocks must be a positive integer")
    return parsed


def nonnegative_integer(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from error
    if str(parsed) != value or parsed < 0:
        raise argparse.ArgumentTypeError(f"{name} must be nonnegative")
    return parsed


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("invalid ISO date") from error


def clock_minute(value: str) -> str:
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise argparse.ArgumentTypeError("invalid HH:MM minute")
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as error:
        raise argparse.ArgumentTypeError("invalid HH:MM minute") from error
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect one market minute into the workbench hot store.")
    parser.add_argument("--fake", action="store_true", help="use deterministic fake provider")
    parser.add_argument("--real", action="store_true", help="use real TDX provider (default)")
    parser.add_argument("--once", action="store_true", help="collect one minute and exit")
    parser.add_argument("--serve", action="store_true", help="run continuously during trading hours")
    parser.add_argument("--date", type=iso_date, help="trade date (YYYY-MM-DD)")
    parser.add_argument("--minute", type=clock_minute, help="minute (HH:MM)")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("../data"),
        help="data directory (default: ../data)",
    )
    parser.add_argument(
        "--tdx-home",
        type=Path,
        default=Path("C:/new_tdx64"),
        help="TDX installation directory",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="load catalog/quotes from fixture directory for offline real-provider tests",
    )
    parser.add_argument("--sync-catalog", action="store_true", help="force refresh market catalog")
    parser.add_argument(
        "--backfill-classic-indices",
        action="store_true",
        help="backfill classic 880 index sectors from MAC tick momentum (today only)",
    )
    parser.add_argument(
        "--sector",
        action="append",
        dest="sector_ids",
        default=[],
        help="limit classic-index backfill to specific sector id(s)",
    )
    parser.add_argument(
        "--overwrite-classic-backfill",
        action="store_true",
        help="replace existing classic-index minute rows when backfilling",
    )
    parser.add_argument("--stocks", type=positive_integer, default=5_500)
    parser.add_argument("--sectors", type=lambda value: nonnegative_integer(value, "sectors"), default=400)
    parser.add_argument(
        "--members-per-sector",
        type=lambda value: nonnegative_integer(value, "members-per-sector"),
        default=80,
    )
    parser.add_argument(
        "--mode",
        choices=("hot", "archive", "combined"),
        default="hot",
        help="hot=优先采集(盘中); archive=全量补采(午休/收盘); combined=单进程两者",
    )
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.fake and arguments.real:
        parser.error("--fake and --real are mutually exclusive")
    if not arguments.fake and not arguments.real:
        arguments.real = True
    if not arguments.once and not arguments.serve and not arguments.backfill_classic_indices:
        parser.error("--once, --serve, or --backfill-classic-indices is required")
    if arguments.once and arguments.serve:
        parser.error("--once and --serve are mutually exclusive")
    if arguments.backfill_classic_indices and (arguments.once or arguments.serve):
        parser.error("--backfill-classic-indices cannot be combined with --once or --serve")
    if arguments.backfill_classic_indices and arguments.date is None:
        parser.error("--backfill-classic-indices requires --date")
    if arguments.once and (arguments.date is None or arguments.minute is None):
        parser.error("--once requires --date and --minute")
    if arguments.sectors and arguments.members_per_sector > arguments.stocks:
        parser.error("members-per-sector cannot exceed stocks when sectors exist")
    return arguments


def build_provider(arguments: argparse.Namespace, settings: WorkbenchSettings):
    if arguments.fake:
        return FakeMarketProvider(arguments.stocks, arguments.sectors, arguments.members_per_sector)
    if arguments.fixture_dir is not None:
        return TdxMarketProvider(settings, fixture_dir=arguments.fixture_dir)
    return create_real_provider(settings)


def collect_once(
    *,
    trade_date: date,
    minute: str,
    data_dir: Path,
    provider,
    sync_catalog: bool = False,
    close_provider: bool = True,
) -> dict[str, int | float | str]:
    settings = WorkbenchSettings(data_dir=data_dir)
    settings.ensure_directories()
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    try:
        if sync_catalog:
            refresh_security_cache(settings, force=True)
        CatalogSyncService(provider, meta).sync(force=sync_catalog)
        hot = HotStore(settings.hot_db_for(trade_date.isoformat()))
        hot.initialize()
        result = MinuteCollector(provider, meta, hot).collect(trade_date, minute)
        if settings.sync_history_bars_on_collect:
            catalog = provider.catalog()
            sample_symbols = [security.symbol for security in catalog.securities[:20]]
            HistorySyncService(provider, settings).sync_symbols(sample_symbols)
        return result
    finally:
        if close_provider:
            close = getattr(provider, "close", None)
            if callable(close):
                close()


def serve(arguments: argparse.Namespace) -> int:
    settings = merge_user_config(
        WorkbenchSettings(data_dir=arguments.data_dir, tdx_home=arguments.tdx_home)
    )
    settings.ensure_directories()
    collector_role = str(arguments.mode)
    try:
        acquire_collector_lock(settings.data_dir, collector_role)
    except RuntimeError as error:
        print(f"collector lock failed: {error}", file=sys.stderr)
        return 1
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    purge_expired_hot_databases(
        settings.data_dir,
        retention_trading_days=meta.retention_days(),
        today=date.today(),
    )
    provider = build_provider(arguments, settings)
    write_collector_heartbeat(settings.data_dir, role=collector_role)
    hot = HotStore(settings.hot_db_for(date.today().isoformat()))
    hot.initialize()
    priority_sectors = PrioritySectorCollector(
        provider,
        meta,
        hot,
        data_dir=settings.data_dir,
        rank_pool=settings.priority_rank_pool,
        max_sectors=settings.priority_max_sectors,
    )
    priority_stocks = PriorityStockCollector(
        provider,
        meta,
        hot,
        settings=settings,
    )
    sector_tick_backfill = SectorTickBackfillService(
        provider,
        meta,
        hot,
        settings,
        data_dir=settings.data_dir,
        rank_pool=settings.priority_rank_pool,
        max_sectors=settings.priority_max_sectors,
    )
    stock_tick_backfill = StockTickBackfillService(meta, hot, settings)
    stock_tick_backfill.bind_enhanced_client(getattr(provider, "_enhanced_client", None))

    def collect(trade_date: date, minute: str) -> dict[str, object]:
        return collect_once(
            trade_date=trade_date,
            minute=minute,
            data_dir=arguments.data_dir,
            provider=provider,
            sync_catalog=arguments.sync_catalog,
            close_provider=False,
        )

    def collect_priority(trade_date: date, minute: str) -> dict[str, object]:
        hot_path = settings.hot_db_for(trade_date.isoformat())
        priority_sectors.hot = HotStore(hot_path)
        priority_sectors.hot.initialize()
        priority_stocks.hot = HotStore(hot_path)
        priority_stocks.hot.initialize()
        sector_tick_backfill._hot = HotStore(hot_path)
        sector_tick_backfill._hot.initialize()
        stock_tick_backfill._hot = HotStore(hot_path)
        stock_tick_backfill._hot.initialize()
        sector_result = priority_sectors.collect(trade_date, minute)
        stock_result = priority_stocks.collect(trade_date, minute)
        tick_sector_result = sector_tick_backfill.backfill_batch(trade_date, minute=minute)
        tick_stock_result = stock_tick_backfill.backfill_batch(trade_date)
        sector_tick_backfill._hot.purge_intraday_closing_minutes(trade_date.isoformat())
        collected_sectors = int(sector_result.get("priority_sectors", 0) or 0)
        collected_stocks = int(stock_result.get("priority_stocks", 0) or 0)
        duration_ms = int(sector_result.get("duration_ms", 0) or 0) + int(stock_result.get("duration_ms", 0) or 0)
        if collected_sectors or collected_stocks:
            catalog = meta.catalog_snapshot()
            priority_sectors.hot.upsert_priority_minute_status(
                trade_date=trade_date.isoformat(),
                minute=minute,
                batch_id=f"{trade_date.isoformat()}T{minute}-priority",
                catalog_version=catalog.catalog_version or "unknown",
                collected_sectors=collected_sectors,
                collected_stocks=collected_stocks,
                expected_sectors=settings.priority_max_sectors,
                expected_stocks=settings.priority_max_stocks,
                duration_ms=duration_ms,
            )
        return {
            "priority_sectors": collected_sectors,
            "priority_stocks": collected_stocks,
            "tick_sectors": tick_sector_result.backfilled,
            "tick_stocks": tick_stock_result.backfilled,
            "tick_minutes": tick_sector_result.minutes_written + tick_stock_result.minutes_written,
            "minute": minute,
            "duration_ms": int(sector_result.get("duration_ms", 0) or 0)
            + int(stock_result.get("duration_ms", 0) or 0),
            "errors": sector_result.get("errors", 0),
        }

    def collect_once_for_backfill(trade_date: date, minute: str) -> dict[str, object]:
        hot_path = settings.hot_db_for(trade_date.isoformat())
        backfill_hot = HotStore(hot_path)
        backfill_hot.initialize()
        if backfill_hot.latest_complete_minute(trade_date.isoformat()) == minute:
            return {"skipped": minute, "status": "already-complete"}
        return collect_once(
            trade_date=trade_date,
            minute=minute,
            data_dir=arguments.data_dir,
            provider=provider,
            sync_catalog=False,
            close_provider=False,
        )

    user_cfg = read_workbench_user_config(settings.data_dir)
    use_full_archive_backfill = (
        user_cfg.collect_mode == "full" and user_cfg.archive_full_enabled
    )

    def archive_backfill_collect(trade_date: date, minute: str) -> dict[str, object]:
        if use_full_archive_backfill:
            return collect_once_for_backfill(trade_date, minute)
        return collect_priority(trade_date, minute)

    backfill = SessionBackfillService(hot, archive_backfill_collect)

    def run_session_backfill(trade_date: date, now: datetime) -> dict[str, object] | None:
        write_collector_heartbeat(settings.data_dir, role=collector_role)
        result = backfill.next_missing_minute(trade_date, now)
        if result is not None and result.get("backfill") == "done":
            sector_tick_backfill._hot = HotStore(settings.hot_db_for(trade_date.isoformat()))
            sector_tick_backfill._hot.initialize()
            stock_tick_backfill._hot = sector_tick_backfill._hot
            tick_sector = sector_tick_backfill.backfill_batch(
                trade_date,
                max_sectors=settings.priority_max_sectors,
            )
            tick_stock = stock_tick_backfill.backfill_batch(
                trade_date,
                max_symbols=min(settings.priority_max_stocks, 80),
            )
            return {
                **result,
                "tick_sectors": tick_sector.backfilled,
                "tick_stocks": tick_stock.backfilled,
                "tick_minutes": tick_sector.minutes_written + tick_stock.minutes_written,
            }
        return result

    if collector_role == "hot":
        priority_fn: CollectFn | None = collect_priority
        backfill_fn = None
    elif collector_role == "archive":
        priority_fn = None
        backfill_fn = run_session_backfill
    else:
        priority_fn = collect_priority
        backfill_fn = run_session_backfill

    scheduler = MinuteScheduler(
        collect=collect,
        priority_collect=priority_fn,
        session_backfill=backfill_fn,
        quote_interval_seconds=settings.quote_interval_seconds,
        priority_interval_seconds=settings.priority_interval_seconds,
        full_collect_interval_seconds=settings.full_collect_interval_seconds,
        on_tick=lambda: write_collector_heartbeat(settings.data_dir, role=collector_role),
        mode=collector_role,
    )
    try:
        scheduler.serve()
    except KeyboardInterrupt:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
        release_collector_lock(settings.data_dir, collector_role)
        return 0
    return 0


def backfill_classic_indices(arguments: argparse.Namespace) -> int:
    settings = WorkbenchSettings(data_dir=arguments.data_dir, tdx_home=arguments.tdx_home)
    settings.ensure_directories()
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    hot = HotStore(settings.hot_db_for(arguments.date.isoformat()))
    hot.initialize()
    service = ClassicIndexBackfillService(meta, hot)
    try:
        result = service.backfill(
            arguments.date,
            sector_ids=arguments.sector_ids or None,
            overwrite=arguments.overwrite_classic_backfill,
        )
    except ValueError as error:
        print(f"classic index backfill failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")))
    return 0 if not result.failed else 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    settings = WorkbenchSettings(data_dir=arguments.data_dir, tdx_home=arguments.tdx_home)
    if arguments.serve:
        return serve(arguments)
    if arguments.backfill_classic_indices:
        return backfill_classic_indices(arguments)
    try:
        result = collect_once(
            trade_date=arguments.date,
            minute=arguments.minute,
            data_dir=arguments.data_dir,
            provider=build_provider(arguments, settings),
            sync_catalog=arguments.sync_catalog,
        )
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        print(f"collector setup failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
