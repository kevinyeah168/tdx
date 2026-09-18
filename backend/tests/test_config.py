from pathlib import Path

import pytest
from pydantic import ValidationError

from workbench.config import WorkbenchSettings, workbench_settings_from_environment


def test_real_tdx_settings_have_bounded_defaults() -> None:
    settings = WorkbenchSettings()

    assert settings.tdx_home == Path("C:/new_tdx64")
    assert settings.normal_node_timeout_seconds == 3.0
    assert settings.enhanced_node_timeout_seconds == 5.0
    assert settings.node_pool_size == 8
    assert settings.node_retry_count == 2
    assert settings.enhanced_quote_enabled is True
    assert settings.quote_batch_size == 80
    assert settings.retention_trading_days == 365


def test_real_tdx_settings_load_from_workbench_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "WORKBENCH_TDX_HOME": "D:/tdx-custom",
        "WORKBENCH_NORMAL_NODE_TIMEOUT_SECONDS": "1.5",
        "WORKBENCH_ENHANCED_NODE_TIMEOUT_SECONDS": "7.5",
        "WORKBENCH_NODE_POOL_SIZE": "12",
        "WORKBENCH_NODE_RETRY_COUNT": "4",
        "WORKBENCH_ENHANCED_QUOTE_ENABLED": "false",
        "WORKBENCH_QUOTE_BATCH_SIZE": "64",
        "WORKBENCH_RETENTION_TRADING_DAYS": "45",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    monkeypatch.setattr("workbench.config.merge_user_config", lambda settings: settings)
    settings = workbench_settings_from_environment()

    assert settings.tdx_home == Path("D:/tdx-custom")
    assert settings.normal_node_timeout_seconds == 1.5
    assert settings.enhanced_node_timeout_seconds == 7.5
    assert settings.node_pool_size == 12
    assert settings.node_retry_count == 4
    assert settings.enhanced_quote_enabled is False
    assert settings.quote_batch_size == 64
    assert settings.retention_trading_days == 45


@pytest.mark.parametrize(
    ("environment_name", "value"),
    [
        ("WORKBENCH_NORMAL_NODE_TIMEOUT_SECONDS", "0"),
        ("WORKBENCH_NORMAL_NODE_TIMEOUT_SECONDS", "61"),
        ("WORKBENCH_NORMAL_NODE_TIMEOUT_SECONDS", "slow"),
        ("WORKBENCH_ENHANCED_NODE_TIMEOUT_SECONDS", "0"),
        ("WORKBENCH_ENHANCED_NODE_TIMEOUT_SECONDS", "61"),
        ("WORKBENCH_ENHANCED_NODE_TIMEOUT_SECONDS", "slow"),
        ("WORKBENCH_NODE_POOL_SIZE", "0"),
        ("WORKBENCH_NODE_POOL_SIZE", "65"),
        ("WORKBENCH_NODE_POOL_SIZE", "many"),
        ("WORKBENCH_NODE_RETRY_COUNT", "-1"),
        ("WORKBENCH_NODE_RETRY_COUNT", "11"),
        ("WORKBENCH_NODE_RETRY_COUNT", "many"),
        ("WORKBENCH_QUOTE_BATCH_SIZE", "0"),
        ("WORKBENCH_QUOTE_BATCH_SIZE", "81"),
        ("WORKBENCH_QUOTE_BATCH_SIZE", "many"),
        ("WORKBENCH_ENHANCED_QUOTE_ENABLED", "sometimes"),
        ("WORKBENCH_ENHANCED_QUOTE_ENABLED", "2"),
        ("WORKBENCH_ENHANCED_QUOTE_ENABLED", ""),
    ],
)
def test_real_tdx_environment_rejects_invalid_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    value: str,
) -> None:
    for field_name in WorkbenchSettings.model_fields:
        monkeypatch.delenv(f"WORKBENCH_{field_name.upper()}", raising=False)
    monkeypatch.setenv(environment_name, value)

    with pytest.raises((ValidationError, ValueError)):
        workbench_settings_from_environment()


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
