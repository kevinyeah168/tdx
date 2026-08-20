from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Sequence

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.config import WorkbenchSettings
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


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
    parser = argparse.ArgumentParser(description="Collect one deterministic fake market minute.")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--date", type=iso_date, required=True)
    parser.add_argument("--minute", type=clock_minute, required=True)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("../data"),
        help="data directory (default: ../data)",
    )
    parser.add_argument("--stocks", type=positive_integer, default=5_500)
    parser.add_argument("--sectors", type=lambda value: nonnegative_integer(value, "sectors"), default=400)
    parser.add_argument(
        "--members-per-sector",
        type=lambda value: nonnegative_integer(value, "members-per-sector"),
        default=80,
    )
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not arguments.fake:
        parser.error("--fake is required for phase one")
    if not arguments.once:
        parser.error("--once is required for phase one")
    if arguments.sectors and arguments.members_per_sector > arguments.stocks:
        parser.error("members-per-sector cannot exceed stocks when sectors exist")
    return arguments


def collect_once(
    *, trade_date: date, minute: str, data_dir: Path, stocks: int, sectors: int, members_per_sector: int
) -> dict[str, int | float | str]:
    settings = WorkbenchSettings(data_dir=data_dir)
    settings.ensure_directories()
    provider = FakeMarketProvider(stocks, sectors, members_per_sector)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(trade_date.isoformat()))
    hot.initialize()
    return MinuteCollector(provider, meta, hot).collect(trade_date, minute)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    try:
        result = collect_once(
            trade_date=arguments.date,
            minute=arguments.minute,
            data_dir=arguments.data_dir,
            stocks=arguments.stocks,
            sectors=arguments.sectors,
            members_per_sector=arguments.members_per_sector,
        )
    except (OSError, sqlite3.Error) as error:
        print(f"collector setup failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
