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
    priority_interval_seconds: float = Field(default=5.0, ge=1.0, le=15.0)
    yuntu_collect_interval_seconds: float = Field(default=18.0, ge=5.0, le=60.0)
    gray_collect_interval_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    full_collect_interval_seconds: float = Field(default=45.0, ge=15.0, le=300.0)
    priority_rank_pool: int = Field(default=0, ge=0, le=200)
    # Selected watchlist is the source of truth; caps are high enough for ~100 sectors
    # and their full membership (no practical "自选上限").
    priority_max_sectors: int = Field(default=500, ge=1, le=2000)
    priority_max_stocks: int = Field(default=30000, ge=1, le=50000)
    priority_sector_members: int = Field(default=5000, ge=1, le=10000)
    priority_linkage_members: int = Field(default=5000, ge=1, le=10000)
    minute_budget_seconds: float = Field(default=45.0, gt=0.0, le=55.0)
    normal_node_timeout_seconds: float = Field(default=3.0, gt=0.0, le=60.0)
    enhanced_node_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    node_pool_size: int = Field(default=8, ge=1, le=64)
    node_retry_count: int = Field(default=2, ge=0, le=10)
    enhanced_quote_enabled: bool = True
    quote_batch_size: int = Field(default=80, ge=1, le=80)
    # 采集优先主力分钟资金；日 K 与分笔五层推算默认关闭
    sync_history_bars_on_collect: bool = False
    estimate_transaction_tiers: bool = False
    # 盘中主力/涨跌来自通达信板块云图 real_hq（15s 轮询，分钟快照入库）
    sector_official_main_enabled: bool = False
    sector_yuntu_main_enabled: bool = True
    intraday_full_minute_ratio: float = Field(default=0.85, ge=0.5, le=1.0)
    tick_backfill_batch_size: int = Field(default=32, ge=1, le=80)

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
    settings = WorkbenchSettings.model_validate(values)
    return merge_user_config(settings)


def merge_user_config(settings: WorkbenchSettings) -> WorkbenchSettings:
    from workbench.storage.workbench_config import read_workbench_user_config

    user_cfg = read_workbench_user_config(settings.data_dir)
    return settings.model_copy(update={"tdx_home": Path(user_cfg.tdx_home)})
