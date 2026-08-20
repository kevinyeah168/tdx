"""Run the deterministic 5,500-stock minute-collection capacity probe."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import time


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.config import WorkbenchSettings
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


BUDGET_SECONDS = 45.0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="workbench-minute-batch-") as temporary_directory:
        setup_started_at = time.perf_counter()
        settings = WorkbenchSettings(data_dir=Path(temporary_directory))
        settings.ensure_directories()
        provider = FakeMarketProvider(5_500, 400, 80)
        meta = MetaStore(settings.meta_db)
        meta.initialize()
        CatalogSyncService(provider, meta).sync()
        hot = HotStore(settings.hot_db_for("2026-08-20"))
        hot.initialize()
        setup_seconds = time.perf_counter() - setup_started_at

        started_at = time.perf_counter()
        status = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")
        wall_seconds = time.perf_counter() - started_at

    payload = {
        **status,
        "setup_seconds": setup_seconds,
        "wall_seconds": wall_seconds,
        "budget_seconds": BUDGET_SECONDS,
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return int(
        wall_seconds > BUDGET_SECONDS
        or status["coverage_pct"] != 100.0
        or status["collected_stocks"] != 5_500
        or status["collected_sectors"] != 400
    )


if __name__ == "__main__":
    raise SystemExit(main())
