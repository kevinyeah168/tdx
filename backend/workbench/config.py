from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class WorkbenchSettings(BaseModel):
    data_dir: Path = Path("../data")
    retention_trading_days: int = Field(default=30, ge=1, le=2500)
    quote_interval_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    minute_budget_seconds: float = Field(default=45.0, gt=0.0, le=55.0)

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
