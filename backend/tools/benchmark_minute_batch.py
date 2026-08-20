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

from workbench.collector.main import collect_once


BUDGET_SECONDS = 45.0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="workbench-minute-batch-") as temporary_directory:
        started_at = time.perf_counter()
        status = collect_once(
            trade_date=date(2026, 8, 20),
            minute="09:31",
            data_dir=Path(temporary_directory),
            stocks=5_500,
            sectors=400,
            members_per_sector=80,
        )
        wall_seconds = time.perf_counter() - started_at

    payload = {
        "status": status,
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
