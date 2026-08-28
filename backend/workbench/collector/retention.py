from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path


def purge_expired_hot_databases(
    data_dir: Path,
    *,
    retention_trading_days: int,
    today: date,
) -> list[str]:
    if retention_trading_days < 1:
        raise ValueError("retention_trading_days must be at least 1")
    hot_dir = data_dir / "hot"
    if not hot_dir.is_dir():
        return []
    cutoff = today - timedelta(days=retention_trading_days)
    removed: list[str] = []
    for path in sorted(hot_dir.glob("*.sqlite")):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date >= cutoff:
            continue
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed
