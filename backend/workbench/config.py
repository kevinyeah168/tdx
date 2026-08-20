from __future__ import annotations

from datetime import date
import os
from pathlib import Path

from pydantic import BaseModel, Field


class WorkbenchSettings(BaseModel):
    data_dir: Path = Path("../data")
    tdx_home: Path = Path("C:/new_tdx64")
    retention_trading_days: int = Field(default=30, ge=1, le=2500)
    quote_interval_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    minute_budget_seconds: float = Field(default=45.0, gt=0.0, le=55.0)
    normal_node_timeout_seconds: float = Field(default=3.0, gt=0.0, le=60.0)
    enhanced_node_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    node_pool_size: int = Field(default=8, ge=1, le=64)
    node_retry_count: int = Field(default=2, ge=0, le=10)
    enhanced_quote_enabled: bool = True
    quote_batch_size: int = Field(default=80, ge=1, le=80)

    @property
    def meta_db(self) -> Path:
        return self.data_dir / "meta" / "market_meta.sqlite"

    def hot_db_for(self, trade_date: str) -> Path:
        parsed_trade_date = date.fromisoformat(trade_date)
        return self.data_dir / "hot" / f"{parsed_trade_date.isoformat()}.sqlite"

    def ensure_directories(self) -> None:
        (self.data_dir / "meta").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "hot").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "history").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "run").mkdir(parents=True, exist_ok=True)


def workbench_settings_from_environment() -> WorkbenchSettings:
    values: dict[str, str] = {}
    for field_name in WorkbenchSettings.model_fields:
        environment_name = f"WORKBENCH_{field_name.upper()}"
        raw_value = os.environ.get(environment_name)
        if raw_value is None:
            continue
        if not raw_value.strip():
            raise ValueError(f"{environment_name} must not be blank")
        values[field_name] = raw_value
    return WorkbenchSettings.model_validate(values)
