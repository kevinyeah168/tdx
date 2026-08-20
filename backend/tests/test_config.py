from pathlib import Path

import pytest

from workbench.config import WorkbenchSettings


def test_settings_create_separate_meta_and_hot_paths(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path, retention_trading_days=30)

    assert settings.meta_db == tmp_path / "meta" / "market_meta.sqlite"
    assert settings.hot_db_for("2026-08-20") == tmp_path / "hot" / "2026-08-20.sqlite"
    assert settings.retention_trading_days == 30


@pytest.mark.parametrize("trade_date", ["../escape", "not-a-date"])
def test_hot_db_for_rejects_malformed_trade_dates(trade_date: str) -> None:
    settings = WorkbenchSettings(data_dir=Path("data"))

    with pytest.raises(ValueError):
        settings.hot_db_for(trade_date)
