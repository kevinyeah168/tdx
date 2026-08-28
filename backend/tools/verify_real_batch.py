from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from workbench.storage.meta_store import MetaStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a collected real market batch.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--date", required=True, help="trade date YYYY-MM-DD")
    parser.add_argument("--minute", required=True, help="minute HH:MM")
    return parser


def verify(data_dir: Path, trade_date: str, minute: str) -> dict[str, object]:
    meta = MetaStore(data_dir / "meta" / "market_meta.sqlite")
    meta.initialize()
    snapshot = meta.catalog_snapshot()
    if snapshot.catalog_version is None:
        raise RuntimeError("catalog version missing")
    if snapshot.stale:
        raise RuntimeError(f"catalog is stale: {snapshot.error_summary}")
    hot_path = data_dir / "hot" / f"{trade_date}.sqlite"
    if not hot_path.is_file():
        raise RuntimeError("hot database missing")
    connection = sqlite3.connect(hot_path)
    try:
        status = connection.execute(
            "SELECT status, coverage_pct, catalog_version, collected_stocks, expected_stocks "
            "FROM collection_status WHERE trade_date=? AND minute=?",
            (trade_date, minute),
        ).fetchone()
        if status is None:
            raise RuntimeError("collection status missing")
        if status[0] != "complete":
            raise RuntimeError(f"batch status is {status[0]}")
        if status[2] != snapshot.catalog_version:
            raise RuntimeError("catalog version mismatch between meta and hot store")
        markets = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT substr(symbol, 1, 2) FROM stock_minute WHERE trade_date=? AND minute=?",
                (trade_date, minute),
            ).fetchall()
        }
        if not {"SH", "SZ"}.issubset(markets):
            raise RuntimeError(f"missing expected markets in batch: {sorted(markets)}")
        return {
            "ok": True,
            "catalog_version": snapshot.catalog_version,
            "coverage_pct": status[1],
            "collected_stocks": status[3],
            "expected_stocks": status[4],
            "markets": sorted(markets),
        }
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        payload = verify(arguments.data_dir, arguments.date, arguments.minute)
    except RuntimeError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
