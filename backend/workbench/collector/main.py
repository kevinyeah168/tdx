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

from workbench.collector.gray_stock_collector import GrayStockCollector
from workbench.collector.yuntu_snapshot_collector import YuntuSnapshotCollector
from workbench.collector.classic_index_backfill import ClassicIndexBackfillService
from workbench.collector.sector_gray_backfill import (
    backfill_sector_gray_for_settings,
)
from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.heartbeat import write_collector_heartbeat
from workbench.collector.history_sync import HistorySyncService, refresh_security_cache
from workbench.collector.minute_collector import MinuteCollector
from workbench.collector.process_lock import acquire_collector_lock, release_collector_lock
from workbench.collector.retention import purge_expired_hot_databases
from workbench.collector.scheduler import CollectFn, MinuteScheduler
from workbench.collector.session_backfill import SessionBackfillService
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
        help="backfill classic 880 index sectors from MAC tick momentum (any trade date)",
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
    parser.add_argument(
        "--backfill-sector-gray",
        action="store_true",
        help="rebuild sector_gray_minute from stock_gray_minute (all hot dates unless --date)",
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
        choices=("hot", "archive", "combined", "gray"),
        default="hot",
        help="hot/combined=云图主盘; gray=东财暗盘(独立进程); archive=已废弃",
    )
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.fake and arguments.real:
        parser.error("--fake and --real are mutually exclusive")
    if not arguments.fake and not arguments.real:
        arguments.real = True
    if (
        not arguments.once
        and not arguments.serve
        and not arguments.backfill_classic_indices
        and not arguments.backfill_sector_gray
    ):
        parser.error(
            "--once, --serve, --backfill-classic-indices, or --backfill-sector-gray is required"
        )
    if arguments.once and arguments.serve:
        parser.error("--once and --serve are mutually exclusive")
    if arguments.backfill_classic_indices and (arguments.once or arguments.serve):
        parser.error("--backfill-classic-indices cannot be combined with --once or --serve")
    if arguments.backfill_sector_gray and (arguments.once or arguments.serve):
        parser.error("--backfill-sector-gray cannot be combined with --once or --serve")
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
    write_collector_heartbeat(settings.data_dir, role=collector_role)
    hot = HotStore(settings.hot_db_for(date.today().isoformat()))
    hot.initialize()

    if collector_role == "gray":
        try:
            backfill_results = backfill_sector_gray_for_settings(settings)
            if backfill_results:
                total_rows = sum(item.sector_rows for item in backfill_results)
                active_days = sum(1 for item in backfill_results if item.sector_rows > 0)
                print(
                    f"sector gray backfill: {active_days} day(s), {total_rows} sector rows",
                    file=sys.stderr,
                )
        except ValueError as error:
            print(f"sector gray backfill skipped: {error}", file=sys.stderr)

        gray_stocks = GrayStockCollector(hot, settings=settings, meta=meta)

        def collect_gray(trade_date: date, minute: str) -> dict[str, object]:
            hot_path = settings.hot_db_for(trade_date.isoformat())
            gray_stocks.hot = HotStore(hot_path)
            gray_stocks.hot.initialize()
            return gray_stocks.collect(trade_date, minute)

        scheduler = MinuteScheduler(
            collect=lambda *_args, **_kwargs: {},
            gray_collect=collect_gray,
            gray_interval_seconds=settings.gray_collect_interval_seconds,
            on_tick=lambda: write_collector_heartbeat(settings.data_dir, role=collector_role),
            mode="gray",
        )
        try:
            scheduler.serve()
        except KeyboardInterrupt:
            release_collector_lock(settings.data_dir, collector_role)
            return 0
        return 0

    provider = build_provider(arguments, settings)
    yuntu_snapshots = YuntuSnapshotCollector(
        meta,
        hot,
        settings=settings,
    )

    def collect(trade_date: date, minute: str) -> dict[str, object]:
        return collect_once(
            trade_date=trade_date,
            minute=minute,
            data_dir=arguments.data_dir,
            provider=provider,
            sync_catalog=arguments.sync_catalog,
            close_provider=False,
        )

    def collect_yuntu(trade_date: date, minute: str) -> dict[str, object]:
        hot_path = settings.hot_db_for(trade_date.isoformat())
        yuntu_snapshots.hot = HotStore(hot_path)
        yuntu_snapshots.hot.initialize()
        result = yuntu_snapshots.collect(trade_date, minute)
        collected_sectors = int(result.get("yuntu_sectors", 0) or 0)
        collected_stocks = int(result.get("yuntu_stocks", 0) or 0)
        duration_ms = int(result.get("duration_ms", 0) or 0)
        if collected_sectors or collected_stocks:
            catalog = meta.catalog_snapshot()
            yuntu_snapshots.hot.upsert_priority_minute_status(
                trade_date=trade_date.isoformat(),
                minute=minute,
                batch_id=f"{trade_date.isoformat()}T{minute}-yuntu",
                catalog_version=catalog.catalog_version or "unknown",
                collected_sectors=collected_sectors,
                collected_stocks=collected_stocks,
                expected_sectors=meta.sector_count(),
                expected_stocks=meta.security_count(),
                duration_ms=duration_ms,
            )
        return result

    def finalize_yuntu(trade_date: date) -> dict[str, object] | None:
        hot_path = settings.hot_db_for(trade_date.isoformat())
        yuntu_snapshots.hot = HotStore(hot_path)
        yuntu_snapshots.hot.initialize()
        return yuntu_snapshots.finalize_pending(trade_date)

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
        return collect_yuntu(trade_date, minute)

    backfill = SessionBackfillService(hot, archive_backfill_collect)

    def run_session_backfill(trade_date: date, now: datetime) -> dict[str, object] | None:
        write_collector_heartbeat(settings.data_dir, role=collector_role)
        return backfill.next_missing_minute(trade_date, now)

    # gray runs in a dedicated process (--mode gray); yuntu paths never embed it.
    if collector_role == "hot":
        priority_fn: CollectFn | None = collect_yuntu
        backfill_fn = None
        yuntu_finalize_fn = finalize_yuntu
    elif collector_role == "archive":
        priority_fn = None
        backfill_fn = run_session_backfill
        yuntu_finalize_fn = None
    else:
        priority_fn = collect_yuntu
        backfill_fn = run_session_backfill
        yuntu_finalize_fn = finalize_yuntu

    scheduler = MinuteScheduler(
        collect=collect,
        priority_collect=priority_fn,
        gray_collect=None,
        gray_interval_seconds=settings.gray_collect_interval_seconds,
        yuntu_finalize=yuntu_finalize_fn,
        session_backfill=backfill_fn,
        quote_interval_seconds=settings.quote_interval_seconds,
        priority_interval_seconds=settings.yuntu_collect_interval_seconds,
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

def backfill_sector_gray(arguments: argparse.Namespace) -> int:
    settings = WorkbenchSettings(data_dir=arguments.data_dir, tdx_home=arguments.tdx_home)
    settings.ensure_directories()
    trade_dates = [arguments.date.isoformat()] if arguments.date is not None else None
    try:
        results = backfill_sector_gray_for_settings(settings, trade_dates=trade_dates)
    except ValueError as error:
        print(f"sector gray backfill failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps([asdict(item) for item in results], ensure_ascii=False, separators=(",", ":")))
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
    if arguments.backfill_sector_gray:
        return backfill_sector_gray(arguments)
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
