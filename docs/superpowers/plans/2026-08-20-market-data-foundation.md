# Market Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working vertical slice of the local multi-service data engine: deterministic full-market minute fund data, stock-to-sector aggregation, idempotent SQLite storage, read-only fund-flow APIs, and a 5,500-stock capacity probe.

**Architecture:** Create a new `workbench` Python package beside the legacy `app` package so the existing dashboard remains runnable during migration. A provider interface supplies normalized stock minute records; the collector aggregates sector tiers and is the sole hot-store writer; FastAPI reads committed batches only. This phase uses a deterministic fake provider to prove contracts and storage throughput before a later plan connects the real TDX provider.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, SQLite WAL, PyYAML, pytest, HTTPX; existing Vue frontend remains unchanged in this phase.

---

## Scope and file map

This specification contains several independently testable subsystems, so implementation is split into plans. This first plan covers only the foundation and local capacity proof. Real TDX full-market adapters, Parquet/DuckDB history, frontend board/stock workspaces, replay controls, K-line detail, and Windows production service registration each receive later plans after this foundation passes.

Create or modify these files:

```text
backend/
├─ requirements-dev.txt                 # Test-only dependencies
├─ pytest.ini                           # Test discovery and markers
├─ workbench/
│  ├─ __init__.py                       # Package version
│  ├─ config.py                         # Validated paths and collection settings
│  ├─ domain.py                         # Shared catalog/minute/fund contracts
│  ├─ providers/
│  │  ├─ __init__.py
│  │  ├─ base.py                        # Provider protocol
│  │  └─ fake.py                        # Deterministic capacity-test provider
│  ├─ storage/
│  │  ├─ __init__.py
│  │  ├─ schema.py                      # SQLite DDL
│  │  ├─ meta_store.py                  # Catalog/settings repository
│  │  └─ hot_store.py                   # Idempotent minute writer/read model
│  ├─ collector/
│  │  ├─ __init__.py
│  │  ├─ catalog_sync.py                # Provider catalog to metadata DB
│  │  ├─ sector_aggregator.py           # Stock tiers to sector tiers
│  │  ├─ minute_collector.py            # One complete minute transaction
│  │  └─ main.py                        # Collector CLI
│  └─ api/
│     ├─ __init__.py
│     └─ main.py                        # Read-only FastAPI application
├─ tests/
│  ├─ conftest.py
│  ├─ test_config.py
│  ├─ test_domain.py
│  ├─ test_meta_store.py
│  ├─ test_hot_store.py
│  ├─ test_fake_provider.py
│  ├─ test_catalog_sync.py
│  ├─ test_sector_aggregator.py
│  ├─ test_minute_collector.py
│  └─ test_api_fund_flow.py
└─ tools/
   └─ benchmark_minute_batch.py         # 5,500-stock/400-sector probe
```

Do not modify legacy `backend/app` behavior in this phase.

### Task 1: Establish the backend test harness

**Files:**
- Create: `backend/requirements-dev.txt`
- Create: `backend/pytest.ini`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_package.py`
- Create: `backend/workbench/__init__.py`

- [ ] **Step 1: Write the failing package test**

Create `backend/tests/test_package.py`:

```python
def test_workbench_package_has_version() -> None:
    from workbench import __version__

    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run the test and verify the package is missing**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_package.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'workbench'`.

- [ ] **Step 3: Add test configuration and the minimal package**

Create `backend/requirements-dev.txt`:

```text
-r requirements.txt
pytest>=8.3,<9
httpx>=0.27,<1
```

Create `backend/pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = .
markers =
    performance: local capacity tests that may take several seconds
```

Create `backend/tests/conftest.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    return path
```

Create `backend/workbench/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Install test dependencies and rerun the test**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests\test_package.py -v
```

Expected: `1 passed`.

- [ ] **Step 5: Commit the test harness**

```powershell
git add backend/requirements-dev.txt backend/pytest.ini backend/tests backend/workbench/__init__.py
git commit -m "test: add workbench backend harness"
```

### Task 2: Define settings and normalized fund-flow contracts

**Files:**
- Create: `backend/workbench/config.py`
- Create: `backend/workbench/domain.py`
- Create: `backend/tests/test_config.py`
- Create: `backend/tests/test_domain.py`

- [ ] **Step 1: Write failing settings and tier-consistency tests**

Create `backend/tests/test_config.py`:

```python
from pathlib import Path

from workbench.config import WorkbenchSettings


def test_settings_create_separate_meta_and_hot_paths(tmp_path: Path) -> None:
    settings = WorkbenchSettings(data_dir=tmp_path, retention_trading_days=30)

    assert settings.meta_db == tmp_path / "meta" / "market_meta.sqlite"
    assert settings.hot_db_for("2026-08-20") == tmp_path / "hot" / "2026-08-20.sqlite"
    assert settings.retention_trading_days == 30
```

Create `backend/tests/test_domain.py`:

```python
from datetime import date, datetime

from workbench.domain import DataQuality, FundFlow, StockMinute


def test_estimated_main_equals_super_plus_large() -> None:
    funds = FundFlow.from_tiers(
        super_delta=30.0,
        super_cum=100.0,
        large_delta=-10.0,
        large_cum=40.0,
        medium_delta=5.0,
        medium_cum=20.0,
        small_delta=-2.0,
        small_cum=-5.0,
        source="pytdx_transactions",
        quality=DataQuality.ESTIMATED,
    )

    assert funds.main.delta == 20.0
    assert funds.main.cumulative == 140.0


def test_stock_minute_keeps_tier_provenance() -> None:
    record = StockMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        symbol="SH600000",
        close=10.2,
        change_pct=1.0,
        amount_delta=1_000_000.0,
        funds=FundFlow.zero("no_trade", DataQuality.OFFICIAL),
        observed_at=datetime(2026, 8, 20, 9, 31, 5),
        batch_id="2026-08-20T09:31",
    )

    assert record.funds.main.source == "no_trade"
    assert record.funds.super.quality is DataQuality.OFFICIAL
```

- [ ] **Step 2: Run the tests and verify imports fail**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_config.py tests\test_domain.py -v
```

Expected: FAIL because `workbench.config` and `workbench.domain` do not exist.

- [ ] **Step 3: Implement validated settings**

Create `backend/workbench/config.py`:

```python
from __future__ import annotations

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
        return self.data_dir / "hot" / f"{trade_date}.sqlite"

    def ensure_directories(self) -> None:
        (self.data_dir / "meta").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "hot").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "history").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "run").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Implement complete domain contracts**

Create `backend/workbench/domain.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class DataQuality(str, Enum):
    OFFICIAL = "official"
    AGGREGATED = "aggregated"
    ESTIMATED = "estimated"
    CALIBRATED = "calibrated"
    STALE = "stale"
    GAP = "gap"


class TierPoint(BaseModel):
    delta: float = 0.0
    cumulative: float = 0.0
    source: str
    quality: DataQuality


class FundFlow(BaseModel):
    main: TierPoint
    super: TierPoint
    large: TierPoint
    medium: TierPoint
    small: TierPoint

    @classmethod
    def zero(cls, source: str, quality: DataQuality) -> "FundFlow":
        def point() -> TierPoint:
            return TierPoint(source=source, quality=quality)

        return cls(main=point(), super=point(), large=point(), medium=point(), small=point())

    @classmethod
    def from_tiers(
        cls,
        *,
        super_delta: float,
        super_cum: float,
        large_delta: float,
        large_cum: float,
        medium_delta: float,
        medium_cum: float,
        small_delta: float,
        small_cum: float,
        source: str,
        quality: DataQuality,
    ) -> "FundFlow":
        def point(delta: float, cumulative: float) -> TierPoint:
            return TierPoint(
                delta=delta,
                cumulative=cumulative,
                source=source,
                quality=quality,
            )

        return cls(
            main=point(super_delta + large_delta, super_cum + large_cum),
            super=point(super_delta, super_cum),
            large=point(large_delta, large_cum),
            medium=point(medium_delta, medium_cum),
            small=point(small_delta, small_cum),
        )


class Security(BaseModel):
    symbol: str
    code: str
    name: str
    market: str
    active: bool = True


class Sector(BaseModel):
    sector_id: str
    name: str
    sector_type: str


class Membership(BaseModel):
    sector_id: str
    symbol: str


class StockMinute(BaseModel):
    trade_date: date
    minute: str = Field(pattern=r"^\d{2}:\d{2}$")
    symbol: str
    close: float
    change_pct: float
    amount_delta: float
    funds: FundFlow
    observed_at: datetime
    batch_id: str


class SectorMinute(BaseModel):
    trade_date: date
    minute: str = Field(pattern=r"^\d{2}:\d{2}$")
    sector_id: str
    change_pct: float
    member_count: int
    funds: FundFlow
    observed_at: datetime
    batch_id: str


class ProviderMinuteBatch(BaseModel):
    trade_date: date
    minute: str
    stocks: list[StockMinute]
    expected_stocks: int
    errors: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_config.py tests\test_domain.py -v
```

Expected: `3 passed`.

Commit:

```powershell
git add backend/workbench/config.py backend/workbench/domain.py backend/tests/test_config.py backend/tests/test_domain.py
git commit -m "feat: define workbench data contracts"
```

### Task 3: Build the metadata repository

**Files:**
- Create: `backend/workbench/storage/__init__.py`
- Create: `backend/workbench/storage/schema.py`
- Create: `backend/workbench/storage/meta_store.py`
- Create: `backend/tests/test_meta_store.py`

- [ ] **Step 1: Write failing catalog and retention tests**

Create `backend/tests/test_meta_store.py`:

```python
from pathlib import Path

from workbench.domain import Membership, Sector, Security
from workbench.storage.meta_store import MetaStore


def test_meta_store_replaces_catalog_atomically(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    store.replace_catalog(
        securities=[Security(symbol="SH600000", code="600000", name="浦发银行", market="SH")],
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=[Membership(sector_id="881001", symbol="SH600000")],
        version="2026-08-20",
    )

    assert store.security_count() == 1
    assert store.sector_count() == 1
    assert store.memberships_for("881001") == ["SH600000"]
    assert store.catalog_version() == "2026-08-20"


def test_retention_defaults_to_thirty_and_can_change(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()

    assert store.retention_days() == 30
    store.set_retention_days(60)
    assert store.retention_days() == 60
```

- [ ] **Step 2: Run the tests and verify the repository is missing**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_meta_store.py -v
```

Expected: FAIL importing `workbench.storage.meta_store`.

- [ ] **Step 3: Add explicit metadata schema**

Create `backend/workbench/storage/__init__.py` as an empty file.

Create `backend/workbench/storage/schema.py`:

```python
META_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS security_master (
    symbol TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    active INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sector_master (
    sector_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sector_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sector_membership (
    sector_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    PRIMARY KEY (sector_id, symbol),
    FOREIGN KEY (sector_id) REFERENCES sector_master(sector_id),
    FOREIGN KEY (symbol) REFERENCES security_master(symbol)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version TEXT NOT NULL
);
"""

HOT_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS stock_minute (
    trade_date TEXT NOT NULL,
    minute TEXT NOT NULL,
    symbol TEXT NOT NULL,
    close REAL NOT NULL,
    change_pct REAL NOT NULL,
    amount_delta REAL NOT NULL,
    main_delta REAL NOT NULL,
    main_cum REAL NOT NULL,
    super_delta REAL NOT NULL,
    super_cum REAL NOT NULL,
    large_delta REAL NOT NULL,
    large_cum REAL NOT NULL,
    medium_delta REAL NOT NULL,
    medium_cum REAL NOT NULL,
    small_delta REAL NOT NULL,
    small_cum REAL NOT NULL,
    tier_meta_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    PRIMARY KEY (trade_date, minute, symbol)
);

CREATE INDEX IF NOT EXISTS idx_stock_series
ON stock_minute(trade_date, symbol, minute);

CREATE TABLE IF NOT EXISTS sector_minute (
    trade_date TEXT NOT NULL,
    minute TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    change_pct REAL NOT NULL,
    member_count INTEGER NOT NULL,
    main_delta REAL NOT NULL,
    main_cum REAL NOT NULL,
    super_delta REAL NOT NULL,
    super_cum REAL NOT NULL,
    large_delta REAL NOT NULL,
    large_cum REAL NOT NULL,
    medium_delta REAL NOT NULL,
    medium_cum REAL NOT NULL,
    small_delta REAL NOT NULL,
    small_cum REAL NOT NULL,
    tier_meta_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    PRIMARY KEY (trade_date, minute, sector_id)
);

CREATE INDEX IF NOT EXISTS idx_sector_series
ON sector_minute(trade_date, sector_id, minute);

CREATE TABLE IF NOT EXISTS collection_status (
    trade_date TEXT NOT NULL,
    minute TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    expected_stocks INTEGER NOT NULL,
    collected_stocks INTEGER NOT NULL,
    expected_sectors INTEGER NOT NULL,
    collected_sectors INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    coverage_pct REAL NOT NULL,
    status TEXT NOT NULL,
    error_summary TEXT NOT NULL,
    PRIMARY KEY (trade_date, minute)
);

CREATE TABLE IF NOT EXISTS data_gap (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    minute TEXT NOT NULL,
    reason TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_type, entity_id, trade_date, minute)
);
"""
```

- [ ] **Step 4: Implement the metadata repository**

Create `backend/workbench/storage/meta_store.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

from workbench.domain import Membership, Sector, Security
from workbench.storage.schema import META_SCHEMA


class MetaStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(META_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES('retention_days', '30')"
            )

    def replace_catalog(
        self,
        *,
        securities: list[Security],
        sectors: list[Sector],
        memberships: list[Membership],
        version: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM sector_membership")
            connection.execute("DELETE FROM sector_master")
            connection.execute("DELETE FROM security_master")
            connection.executemany(
                "INSERT INTO security_master VALUES(?, ?, ?, ?, ?)",
                [(s.symbol, s.code, s.name, s.market, int(s.active)) for s in securities],
            )
            connection.executemany(
                "INSERT INTO sector_master VALUES(?, ?, ?)",
                [(s.sector_id, s.name, s.sector_type) for s in sectors],
            )
            connection.executemany(
                "INSERT INTO sector_membership VALUES(?, ?)",
                [(m.sector_id, m.symbol) for m in memberships],
            )
            connection.execute(
                "INSERT INTO catalog_state(singleton, version) VALUES(1, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET version=excluded.version",
                (version,),
            )

    def security_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM security_master").fetchone()[0])

    def sector_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM sector_master").fetchone()[0])

    def memberships_for(self, sector_id: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT symbol FROM sector_membership WHERE sector_id=? ORDER BY symbol",
                (sector_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def all_memberships(self) -> list[Membership]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT sector_id, symbol FROM sector_membership ORDER BY sector_id, symbol"
            ).fetchall()
        return [Membership(sector_id=row[0], symbol=row[1]) for row in rows]

    def catalog_version(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT version FROM catalog_state WHERE singleton=1").fetchone()
        return str(row[0]) if row else None

    def retention_days(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='retention_days'"
            ).fetchone()
        return int(row[0]) if row else 30

    def set_retention_days(self, days: int) -> None:
        if not 1 <= days <= 2500:
            raise ValueError("retention days must be between 1 and 2500")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES('retention_days', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(days),),
            )
```

- [ ] **Step 5: Run tests and commit**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_meta_store.py -v
git add backend/workbench/storage backend/tests/test_meta_store.py
git commit -m "feat: add market metadata store"
```

Expected: `2 passed` and a clean commit.

### Task 4: Implement the idempotent hot minute store

**Files:**
- Create: `backend/workbench/storage/hot_store.py`
- Create: `backend/tests/test_hot_store.py`

- [ ] **Step 1: Write failing idempotency and tier-read tests**

Create `backend/tests/test_hot_store.py`:

```python
from datetime import date, datetime
from pathlib import Path

from workbench.domain import DataQuality, FundFlow, StockMinute
from workbench.storage.hot_store import HotStore


def stock_record(close: float) -> StockMinute:
    return StockMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        symbol="SH600000",
        close=close,
        change_pct=1.0,
        amount_delta=1000.0,
        funds=FundFlow.from_tiers(
            super_delta=30.0,
            super_cum=100.0,
            large_delta=-10.0,
            large_cum=40.0,
            medium_delta=5.0,
            medium_cum=20.0,
            small_delta=-2.0,
            small_cum=-5.0,
            source="fake",
            quality=DataQuality.ESTIMATED,
        ),
        observed_at=datetime(2026, 8, 20, 9, 31, 5),
        batch_id="2026-08-20T09:31",
    )


def test_stock_minute_upsert_is_idempotent(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    store.write_stocks([stock_record(10.0)])
    store.write_stocks([stock_record(10.2)])

    rows = store.stock_fund_series("2026-08-20", "SH600000")
    assert len(rows) == 1
    assert rows[0]["close"] == 10.2
    assert rows[0]["main_cum"] == 140.0
    assert rows[0]["super_cum"] == 100.0
    assert rows[0]["large_cum"] == 40.0


def test_uncommitted_minute_is_not_reported_complete(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    store.write_stocks([stock_record(10.0)])

    assert store.latest_complete_minute("2026-08-20") is None
```

- [ ] **Step 2: Run the tests and verify the store is missing**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_hot_store.py -v
```

Expected: FAIL importing `workbench.storage.hot_store`.

- [ ] **Step 3: Implement stock writes and read models**

Create `backend/workbench/storage/hot_store.py` with these public methods:

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from workbench.domain import SectorMinute, StockMinute
from workbench.storage.schema import HOT_SCHEMA


STOCK_UPSERT = """
INSERT INTO stock_minute(
    trade_date, minute, symbol, close, change_pct, amount_delta,
    main_delta, main_cum, super_delta, super_cum, large_delta, large_cum,
    medium_delta, medium_cum, small_delta, small_cum,
    tier_meta_json, observed_at, batch_id
) VALUES(
    :trade_date, :minute, :symbol, :close, :change_pct, :amount_delta,
    :main_delta, :main_cum, :super_delta, :super_cum, :large_delta, :large_cum,
    :medium_delta, :medium_cum, :small_delta, :small_cum,
    :tier_meta_json, :observed_at, :batch_id
) ON CONFLICT(trade_date, minute, symbol) DO UPDATE SET
    close=excluded.close,
    change_pct=excluded.change_pct,
    amount_delta=excluded.amount_delta,
    main_delta=excluded.main_delta,
    main_cum=excluded.main_cum,
    super_delta=excluded.super_delta,
    super_cum=excluded.super_cum,
    large_delta=excluded.large_delta,
    large_cum=excluded.large_cum,
    medium_delta=excluded.medium_delta,
    medium_cum=excluded.medium_cum,
    small_delta=excluded.small_delta,
    small_cum=excluded.small_cum,
    tier_meta_json=excluded.tier_meta_json,
    observed_at=excluded.observed_at,
    batch_id=excluded.batch_id
"""


def _tier_meta(record: StockMinute | SectorMinute) -> str:
    return json.dumps(
        {
            name: {"source": point.source, "quality": point.quality.value}
            for name, point in {
                "main": record.funds.main,
                "super": record.funds.super,
                "large": record.funds.large,
                "medium": record.funds.medium,
                "small": record.funds.small,
            }.items()
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _stock_params(record: StockMinute) -> dict[str, Any]:
    return {
        "trade_date": record.trade_date.isoformat(),
        "minute": record.minute,
        "symbol": record.symbol,
        "close": record.close,
        "change_pct": record.change_pct,
        "amount_delta": record.amount_delta,
        "main_delta": record.funds.main.delta,
        "main_cum": record.funds.main.cumulative,
        "super_delta": record.funds.super.delta,
        "super_cum": record.funds.super.cumulative,
        "large_delta": record.funds.large.delta,
        "large_cum": record.funds.large.cumulative,
        "medium_delta": record.funds.medium.delta,
        "medium_cum": record.funds.medium.cumulative,
        "small_delta": record.funds.small.delta,
        "small_cum": record.funds.small.cumulative,
        "tier_meta_json": _tier_meta(record),
        "observed_at": record.observed_at.isoformat(),
        "batch_id": record.batch_id,
    }


class HotStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if readonly:
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(HOT_SCHEMA)

    def write_stocks(self, records: list[StockMinute]) -> None:
        with self.connect() as connection:
            connection.executemany(STOCK_UPSERT, [_stock_params(record) for record in records])

    def stock_fund_series(self, trade_date: str, symbol: str) -> list[dict[str, Any]]:
        with self.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM stock_minute WHERE trade_date=? AND symbol=? ORDER BY minute",
                (trade_date, symbol),
            ).fetchall()
        return [dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows]

    def latest_complete_minute(self, trade_date: str) -> str | None:
        with self.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT MAX(minute) FROM collection_status WHERE trade_date=? AND status='complete'",
                (trade_date,),
            ).fetchone()
        return str(row[0]) if row and row[0] else None
```

- [ ] **Step 4: Run the tests and correct only concrete failures**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_hot_store.py -v
```

Expected: `2 passed`. The named SQL parameters must match all 19 `stock_minute` columns.

- [ ] **Step 5: Commit the hot store**

```powershell
git add backend/workbench/storage/hot_store.py backend/tests/test_hot_store.py
git commit -m "feat: add idempotent hot minute store"
```

### Task 5: Add a provider contract and deterministic fake market

**Files:**
- Create: `backend/workbench/providers/__init__.py`
- Create: `backend/workbench/providers/base.py`
- Create: `backend/workbench/providers/fake.py`
- Create: `backend/tests/test_fake_provider.py`

- [ ] **Step 1: Write the failing full-market fixture test**

Create `backend/tests/test_fake_provider.py`:

```python
from datetime import date

from workbench.providers.fake import FakeMarketProvider


def test_fake_provider_is_deterministic_and_has_all_tiers() -> None:
    provider = FakeMarketProvider(stock_count=5_500, sector_count=400, members_per_sector=80)
    catalog = provider.catalog()
    batch = provider.minute_batch(date(2026, 8, 20), "09:31")

    assert len(catalog.securities) == 5_500
    assert len(catalog.sectors) == 400
    assert len(batch.stocks) == 5_500
    assert batch.stocks[0].funds.main.cumulative == (
        batch.stocks[0].funds.super.cumulative + batch.stocks[0].funds.large.cumulative
    )
    assert provider.minute_batch(date(2026, 8, 20), "09:31") == batch
```

- [ ] **Step 2: Run the test and verify provider modules are missing**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_fake_provider.py -v
```

Expected: FAIL importing `workbench.providers.fake`.

- [ ] **Step 3: Define the provider protocol**

Create empty `backend/workbench/providers/__init__.py` and create `backend/workbench/providers/base.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel

from workbench.domain import Membership, ProviderMinuteBatch, Sector, Security


class MarketCatalog(BaseModel):
    securities: list[Security]
    sectors: list[Sector]
    memberships: list[Membership]
    version: str


class MarketDataProvider(Protocol):
    def catalog(self) -> MarketCatalog: ...

    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch: ...
```

- [ ] **Step 4: Implement deterministic fake data without random state**

Create `backend/workbench/providers/fake.py`:

```python
from __future__ import annotations

from datetime import date, datetime, time

from workbench.domain import (
    DataQuality,
    FundFlow,
    Membership,
    ProviderMinuteBatch,
    Sector,
    Security,
    StockMinute,
)
from workbench.providers.base import MarketCatalog


class FakeMarketProvider:
    def __init__(
        self,
        stock_count: int,
        sector_count: int,
        members_per_sector: int,
    ) -> None:
        self.stock_count = stock_count
        self.sector_count = sector_count
        self.members_per_sector = members_per_sector
        self._securities = [self._security(index) for index in range(stock_count)]

    @staticmethod
    def _security(index: int) -> Security:
        market_index = index % 3
        serial = index // 3
        if market_index == 0:
            market, code = "SH", f"{600000 + serial:06d}"
        elif market_index == 1:
            market, code = "SZ", f"{1 + serial:06d}"
        else:
            market, code = "BJ", f"{920000 + serial:06d}"
        return Security(
            symbol=f"{market}{code}",
            code=code,
            name=f"测试股票{index:04d}",
            market=market,
        )

    def catalog(self) -> MarketCatalog:
        sectors = [
            Sector(
                sector_id=f"{880000 + index:06d}",
                name=f"测试板块{index:03d}",
                sector_type="industry" if index % 2 == 0 else "concept",
            )
            for index in range(self.sector_count)
        ]
        memberships = [
            Membership(
                sector_id=sector.sector_id,
                symbol=self._securities[
                    (sector_index * self.members_per_sector + offset) % self.stock_count
                ].symbol,
            )
            for sector_index, sector in enumerate(sectors)
            for offset in range(self.members_per_sector)
        ]
        return MarketCatalog(
            securities=self._securities,
            sectors=sectors,
            memberships=memberships,
            version="fake-v1",
        )

    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch:
        minute_number = int(minute[:2]) * 60 + int(minute[3:])
        cumulative_factor = max(1, minute_number - 569)
        observed_at = datetime.combine(trade_date, time.fromisoformat(minute))
        batch_id = f"{trade_date.isoformat()}T{minute}"
        stocks: list[StockMinute] = []
        for index, security in enumerate(self._securities):
            direction = -1.0 if index % 3 == 0 else 1.0
            super_delta = direction * float((index % 17) * 10_000 + minute_number)
            large_delta = direction * float((index % 11) * 5_000 + minute_number)
            medium_delta = direction * float((index % 7) * 2_000)
            small_delta = direction * float((index % 5) * 1_000)
            stocks.append(
                StockMinute(
                    trade_date=trade_date,
                    minute=minute,
                    symbol=security.symbol,
                    close=round(5.0 + (index % 1000) / 100.0, 2),
                    change_pct=round(((index % 21) - 10) / 10.0, 2),
                    amount_delta=float(100_000 + index * 100),
                    funds=FundFlow.from_tiers(
                        super_delta=super_delta,
                        super_cum=super_delta * cumulative_factor,
                        large_delta=large_delta,
                        large_cum=large_delta * cumulative_factor,
                        medium_delta=medium_delta,
                        medium_cum=medium_delta * cumulative_factor,
                        small_delta=small_delta,
                        small_cum=small_delta * cumulative_factor,
                        source="fake_provider",
                        quality=DataQuality.ESTIMATED,
                    ),
                    observed_at=observed_at,
                    batch_id=batch_id,
                )
            )
        return ProviderMinuteBatch(
            trade_date=trade_date,
            minute=minute,
            stocks=stocks,
            expected_stocks=self.stock_count,
        )
```

- [ ] **Step 5: Run tests and commit**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_fake_provider.py -v
git add backend/workbench/providers backend/tests/test_fake_provider.py
git commit -m "test: add deterministic full-market provider"
```

Expected: `1 passed`.

### Task 6: Synchronize market catalog into metadata storage

**Files:**
- Create: `backend/workbench/collector/__init__.py`
- Create: `backend/workbench/collector/catalog_sync.py`
- Create: `backend/tests/test_catalog_sync.py`

- [ ] **Step 1: Write the failing synchronization test**

Create `backend/tests/test_catalog_sync.py`:

```python
from pathlib import Path

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.meta_store import MetaStore


def test_catalog_sync_replaces_previous_version(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    service = CatalogSyncService(FakeMarketProvider(12, 3, 4), store)

    result = service.sync()

    assert result == {"securities": 12, "sectors": 3, "memberships": 12}
    assert store.catalog_version() is not None
    assert store.security_count() == 12
    assert store.sector_count() == 3
```

- [ ] **Step 2: Run the test and verify the service is missing**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_catalog_sync.py -v
```

Expected: FAIL importing `workbench.collector.catalog_sync`.

- [ ] **Step 3: Implement the synchronization service**

Create empty `backend/workbench/collector/__init__.py` and create `backend/workbench/collector/catalog_sync.py`:

```python
from __future__ import annotations

from workbench.providers.base import MarketDataProvider
from workbench.storage.meta_store import MetaStore


class CatalogSyncService:
    def __init__(self, provider: MarketDataProvider, store: MetaStore) -> None:
        self.provider = provider
        self.store = store

    def sync(self) -> dict[str, int]:
        catalog = self.provider.catalog()
        self.store.replace_catalog(
            securities=catalog.securities,
            sectors=catalog.sectors,
            memberships=catalog.memberships,
            version=catalog.version,
        )
        return {
            "securities": len(catalog.securities),
            "sectors": len(catalog.sectors),
            "memberships": len(catalog.memberships),
        }
```

- [ ] **Step 4: Run tests and commit**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_catalog_sync.py tests\test_meta_store.py -v
git add backend/workbench/collector backend/tests/test_catalog_sync.py
git commit -m "feat: synchronize market catalog"
```

Expected: `3 passed`.

### Task 7: Aggregate stock tiers into sector minute records

**Files:**
- Create: `backend/workbench/collector/sector_aggregator.py`
- Create: `backend/tests/test_sector_aggregator.py`

- [ ] **Step 1: Write a failing aggregation test for main, super, and large**

Create `backend/tests/test_sector_aggregator.py`:

```python
from datetime import date, datetime

from workbench.collector.sector_aggregator import SectorAggregator
from workbench.domain import DataQuality, FundFlow, Membership, StockMinute


def stock(symbol: str, super_value: float, large_value: float) -> StockMinute:
    return StockMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        symbol=symbol,
        close=10.0,
        change_pct=1.0,
        amount_delta=1000.0,
        funds=FundFlow.from_tiers(
            super_delta=super_value,
            super_cum=super_value,
            large_delta=large_value,
            large_cum=large_value,
            medium_delta=0.0,
            medium_cum=0.0,
            small_delta=0.0,
            small_cum=0.0,
            source="fake",
            quality=DataQuality.ESTIMATED,
        ),
        observed_at=datetime(2026, 8, 20, 9, 31, 5),
        batch_id="2026-08-20T09:31",
    )


def test_sector_aggregation_preserves_fund_tiers() -> None:
    aggregator = SectorAggregator(
        [
            Membership(sector_id="881001", symbol="SH600000"),
            Membership(sector_id="881001", symbol="SZ000001"),
        ]
    )

    result = aggregator.aggregate([stock("SH600000", 100.0, 40.0), stock("SZ000001", -20.0, 10.0)])

    assert len(result) == 1
    assert result[0].funds.super.cumulative == 80.0
    assert result[0].funds.large.cumulative == 50.0
    assert result[0].funds.main.cumulative == 130.0
    assert result[0].funds.main.quality is DataQuality.AGGREGATED
```

- [ ] **Step 2: Run the test and verify the aggregator is missing**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_sector_aggregator.py -v
```

Expected: FAIL importing `SectorAggregator`.

- [ ] **Step 3: Implement an indexed O(memberships + stocks) aggregator**

Create `backend/workbench/collector/sector_aggregator.py`:

```python
from __future__ import annotations

from collections import defaultdict

from workbench.domain import DataQuality, FundFlow, Membership, SectorMinute, StockMinute, TierPoint


class SectorAggregator:
    def __init__(self, memberships: list[Membership]) -> None:
        self.sectors_by_symbol: dict[str, list[str]] = defaultdict(list)
        for membership in memberships:
            self.sectors_by_symbol[membership.symbol].append(membership.sector_id)

    def aggregate(self, stocks: list[StockMinute]) -> list[SectorMinute]:
        buckets: dict[str, list[StockMinute]] = defaultdict(list)
        for stock in stocks:
            for sector_id in self.sectors_by_symbol.get(stock.symbol, []):
                buckets[sector_id].append(stock)

        output: list[SectorMinute] = []
        for sector_id, members in buckets.items():
            def tier(name: str) -> TierPoint:
                points = [getattr(member.funds, name) for member in members]
                return TierPoint(
                    delta=sum(point.delta for point in points),
                    cumulative=sum(point.cumulative for point in points),
                    source="constituent_sum",
                    quality=DataQuality.AGGREGATED,
                )

            output.append(
                SectorMinute(
                    trade_date=members[0].trade_date,
                    minute=members[0].minute,
                    sector_id=sector_id,
                    change_pct=sum(member.change_pct for member in members) / len(members),
                    member_count=len(members),
                    funds=FundFlow(
                        main=tier("main"),
                        super=tier("super"),
                        large=tier("large"),
                        medium=tier("medium"),
                        small=tier("small"),
                    ),
                    observed_at=max(member.observed_at for member in members),
                    batch_id=members[0].batch_id,
                )
            )
        return sorted(output, key=lambda item: item.sector_id)
```

- [ ] **Step 4: Run the focused test and the domain tests**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_sector_aggregator.py tests\test_domain.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the aggregation unit**

```powershell
git add backend/workbench/collector/sector_aggregator.py backend/tests/test_sector_aggregator.py
git commit -m "feat: aggregate sector fund-flow tiers"
```

### Task 8: Commit a complete minute batch atomically

**Files:**
- Modify: `backend/workbench/storage/hot_store.py`
- Create: `backend/workbench/collector/minute_collector.py`
- Create: `backend/tests/test_minute_collector.py`

- [ ] **Step 1: Write the failing complete-minute test**

Create `backend/tests/test_minute_collector.py`:

```python
from datetime import date
from pathlib import Path

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def test_collector_commits_stocks_sectors_and_coverage(tmp_path: Path) -> None:
    provider = FakeMarketProvider(100, 4, 20)
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(tmp_path / "2026-08-20.sqlite")
    hot.initialize()

    result = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")

    assert result["collected_stocks"] == 100
    assert result["collected_sectors"] == 4
    assert result["coverage_pct"] == 100.0
    assert hot.latest_complete_minute("2026-08-20") == "09:31"
    assert len(hot.stock_fund_series("2026-08-20", "SH600000")) == 1
    assert len(hot.sector_fund_series("2026-08-20", "880000")) == 1
```

- [ ] **Step 2: Run the test and verify missing methods fail**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_minute_collector.py -v
```

Expected: FAIL because `MinuteCollector`, `write_complete_batch`, or `sector_fund_series` is missing.

- [ ] **Step 3: Add one-transaction stock/sector/status writes**

Add `import time` to `backend/workbench/storage/hot_store.py`, then add these constants and helper below `STOCK_UPSERT` and `_stock_params`:

```python
SECTOR_UPSERT = """
INSERT INTO sector_minute(
    trade_date, minute, sector_id, change_pct, member_count,
    main_delta, main_cum, super_delta, super_cum, large_delta, large_cum,
    medium_delta, medium_cum, small_delta, small_cum,
    tier_meta_json, observed_at, batch_id
) VALUES(
    :trade_date, :minute, :sector_id, :change_pct, :member_count,
    :main_delta, :main_cum, :super_delta, :super_cum, :large_delta, :large_cum,
    :medium_delta, :medium_cum, :small_delta, :small_cum,
    :tier_meta_json, :observed_at, :batch_id
) ON CONFLICT(trade_date, minute, sector_id) DO UPDATE SET
    change_pct=excluded.change_pct,
    member_count=excluded.member_count,
    main_delta=excluded.main_delta,
    main_cum=excluded.main_cum,
    super_delta=excluded.super_delta,
    super_cum=excluded.super_cum,
    large_delta=excluded.large_delta,
    large_cum=excluded.large_cum,
    medium_delta=excluded.medium_delta,
    medium_cum=excluded.medium_cum,
    small_delta=excluded.small_delta,
    small_cum=excluded.small_cum,
    tier_meta_json=excluded.tier_meta_json,
    observed_at=excluded.observed_at,
    batch_id=excluded.batch_id
"""

STATUS_UPSERT = """
INSERT INTO collection_status(
    trade_date, minute, batch_id,
    expected_stocks, collected_stocks,
    expected_sectors, collected_sectors,
    duration_ms, coverage_pct, status, error_summary
) VALUES(
    :trade_date, :minute, :batch_id,
    :expected_stocks, :collected_stocks,
    :expected_sectors, :collected_sectors,
    :duration_ms, :coverage_pct, :status, :error_summary
) ON CONFLICT(trade_date, minute) DO UPDATE SET
    batch_id=excluded.batch_id,
    expected_stocks=excluded.expected_stocks,
    collected_stocks=excluded.collected_stocks,
    expected_sectors=excluded.expected_sectors,
    collected_sectors=excluded.collected_sectors,
    duration_ms=excluded.duration_ms,
    coverage_pct=excluded.coverage_pct,
    status=excluded.status,
    error_summary=excluded.error_summary
"""


def _sector_params(record: SectorMinute) -> dict[str, Any]:
    return {
        "trade_date": record.trade_date.isoformat(),
        "minute": record.minute,
        "sector_id": record.sector_id,
        "change_pct": record.change_pct,
        "member_count": record.member_count,
        "main_delta": record.funds.main.delta,
        "main_cum": record.funds.main.cumulative,
        "super_delta": record.funds.super.delta,
        "super_cum": record.funds.super.cumulative,
        "large_delta": record.funds.large.delta,
        "large_cum": record.funds.large.cumulative,
        "medium_delta": record.funds.medium.delta,
        "medium_cum": record.funds.medium.cumulative,
        "small_delta": record.funds.small.delta,
        "small_cum": record.funds.small.cumulative,
        "tier_meta_json": _tier_meta(record),
        "observed_at": record.observed_at.isoformat(),
        "batch_id": record.batch_id,
    }
```

Add these methods to `HotStore`:

```python
    def write_complete_batch(
        self,
        stocks: list[StockMinute],
        sectors: list[SectorMinute],
        status: dict[str, int | float | str],
        *,
        started_at: float,
    ) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(STOCK_UPSERT, [_stock_params(record) for record in stocks])
            connection.executemany(SECTOR_UPSERT, [_sector_params(record) for record in sectors])
            status["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
            connection.execute(STATUS_UPSERT, status)

    def sector_fund_series(self, trade_date: str, sector_id: str) -> list[dict[str, Any]]:
        with self.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM sector_minute WHERE trade_date=? AND sector_id=? ORDER BY minute",
                (trade_date, sector_id),
            ).fetchall()
        return [dict(row) | {"tier_meta": json.loads(row["tier_meta_json"])} for row in rows]
```

The context manager commits after `STATUS_UPSERT`; an exception in either entity write rolls back stock, sector, and status rows together. The status insert executes last, so `latest_complete_minute()` cannot expose a partially written batch.

- [ ] **Step 4: Implement the minute collector with measured coverage**

Create `backend/workbench/collector/minute_collector.py`:

```python
from __future__ import annotations

import time
from datetime import date

from workbench.collector.sector_aggregator import SectorAggregator
from workbench.providers.base import MarketDataProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


class MinuteCollector:
    def __init__(self, provider: MarketDataProvider, meta: MetaStore, hot: HotStore) -> None:
        self.provider = provider
        self.meta = meta
        self.hot = hot

    def collect(self, trade_date: date, minute: str) -> dict[str, int | float | str]:
        started = time.perf_counter()
        batch = self.provider.minute_batch(trade_date, minute)
        memberships = self.meta.all_memberships()
        sectors = SectorAggregator(memberships).aggregate(batch.stocks)
        coverage = (
            len(batch.stocks) / batch.expected_stocks * 100.0
            if batch.expected_stocks
            else 0.0
        )
        status = {
            "trade_date": trade_date.isoformat(),
            "minute": minute,
            "batch_id": f"{trade_date.isoformat()}T{minute}",
            "expected_stocks": batch.expected_stocks,
            "collected_stocks": len(batch.stocks),
            "expected_sectors": self.meta.sector_count(),
            "collected_sectors": len(sectors),
            "duration_ms": 0,
            "coverage_pct": round(coverage, 4),
            "status": "complete" if coverage >= 99.5 else "partial",
            "error_summary": " | ".join(batch.errors),
        }
        self.hot.write_complete_batch(batch.stocks, sectors, status, started_at=started)
        return status
```

- [ ] **Step 5: Run all storage/collector tests and commit**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_hot_store.py tests\test_minute_collector.py -v
git add backend/workbench/storage/hot_store.py backend/workbench/collector/minute_collector.py backend/tests/test_minute_collector.py
git commit -m "feat: commit complete market minute batches"
```

Expected: all focused tests PASS and `latest_complete_minute` advances only after status commit.

### Task 9: Expose read-only stock and sector fund-flow APIs

**Files:**
- Create: `backend/workbench/api/__init__.py`
- Create: `backend/workbench/api/main.py`
- Create: `backend/tests/test_api_fund_flow.py`

- [ ] **Step 1: Write failing API contract tests**

Create `backend/tests/test_api_fund_flow.py`:

```python
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api.main import create_app
from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.config import WorkbenchSettings
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def prepared_client(tmp_path: Path) -> TestClient:
    settings = WorkbenchSettings(data_dir=tmp_path)
    settings.ensure_directories()
    provider = FakeMarketProvider(20, 2, 10)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for("2026-08-20"))
    hot.initialize()
    MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")
    return TestClient(create_app(settings))


def test_stock_fund_flow_returns_main_super_and_large(tmp_path: Path) -> None:
    response = prepared_client(tmp_path).get(
        "/api/v1/stocks/SH600000/fund-flow",
        params={"date": "2026-08-20", "tiers": "main,super,large"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "SH600000"
    assert body["latest_complete_minute"] == "09:31"
    assert set(body["fund_tiers"]) == {"main", "super", "large"}
    assert set(body["points"][0]["values"]) == {"main", "super", "large"}


def test_sector_fund_flow_uses_same_shape(tmp_path: Path) -> None:
    response = prepared_client(tmp_path).get(
        "/api/v1/sectors/880000/minutes",
        params={"date": "2026-08-20", "tiers": "main,super,large"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sector_id"] == "880000"
    assert set(body["fund_tiers"]) == {"main", "super", "large"}
```

- [ ] **Step 2: Run the tests and verify the API package is missing**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_api_fund_flow.py -v
```

Expected: FAIL importing `workbench.api.main`.

- [ ] **Step 3: Implement one shared curve serializer and read-only endpoints**

Create empty `backend/workbench/api/__init__.py` and create `backend/workbench/api/main.py`:

```python
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from workbench.config import WorkbenchSettings
from workbench.storage.hot_store import HotStore

ALLOWED_TIERS = {"main", "super", "large", "medium", "small"}


def _parse_tiers(raw: str) -> list[str]:
    tiers = [part.strip() for part in raw.split(",") if part.strip()]
    if not tiers or any(tier not in ALLOWED_TIERS for tier in tiers):
        raise HTTPException(400, "invalid fund tiers")
    return tiers


def _curve_payload(
    *,
    entity_key: str,
    entity_id: str,
    rows: list[dict],
    latest_minute: str | None,
    tiers: list[str],
) -> dict:
    return {
        entity_key: entity_id,
        "latest_complete_minute": latest_minute,
        "fund_tiers": tiers,
        "points": [
            {
                "minute": row["minute"],
                "values": {
                    tier: {
                        "delta": row[f"{tier}_delta"],
                        "cumulative": row[f"{tier}_cum"],
                        **row["tier_meta"][tier],
                    }
                    for tier in tiers
                },
            }
            for row in rows
        ],
    }


def create_app(settings: WorkbenchSettings | None = None) -> FastAPI:
    resolved = settings or WorkbenchSettings()
    app = FastAPI(title="TDX Market Workbench API", version="0.1.0")

    @app.get("/api/v1/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/stocks/{symbol}/fund-flow")
    def stock_fund_flow(
        symbol: str,
        date: str = Query(...),
        tiers: str = "main,super,large",
    ) -> dict:
        store = HotStore(resolved.hot_db_for(date))
        selected = _parse_tiers(tiers)
        rows = store.stock_fund_series(date, symbol.upper())
        if not rows:
            raise HTTPException(404, "stock fund-flow data not found")
        return _curve_payload(
            entity_key="symbol",
            entity_id=symbol.upper(),
            rows=rows,
            latest_minute=store.latest_complete_minute(date),
            tiers=selected,
        )

    @app.get("/api/v1/sectors/{sector_id}/minutes")
    def sector_minutes(
        sector_id: str,
        date: str = Query(...),
        tiers: str = "main,super,large",
    ) -> dict:
        store = HotStore(resolved.hot_db_for(date))
        selected = _parse_tiers(tiers)
        rows = store.sector_fund_series(date, sector_id)
        if not rows:
            raise HTTPException(404, "sector fund-flow data not found")
        return _curve_payload(
            entity_key="sector_id",
            entity_id=sector_id,
            rows=rows,
            latest_minute=store.latest_complete_minute(date),
            tiers=selected,
        )

    return app


app = create_app()
```

- [ ] **Step 4: Run API and full backend tests**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
```

Expected: all tests PASS, including identical tier structure for stock and sector curves.

- [ ] **Step 5: Commit the query API**

```powershell
git add backend/workbench/api backend/tests/test_api_fund_flow.py
git commit -m "feat: expose stock and sector fund-flow APIs"
```

### Task 10: Add a collector CLI and capacity probe

**Files:**
- Create: `backend/workbench/collector/main.py`
- Create: `backend/tools/benchmark_minute_batch.py`
- Create: `backend/tests/test_collector_cli.py`

- [ ] **Step 1: Write a failing one-shot CLI test**

Create `backend/tests/test_collector_cli.py`:

```python
import json
import subprocess
import sys
from pathlib import Path


def test_fake_collector_cli_writes_one_minute(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "workbench.collector.main",
            "--fake",
            "--once",
            "--date",
            "2026-08-20",
            "--minute",
            "09:31",
            "--data-dir",
            str(tmp_path),
            "--stocks",
            "100",
            "--sectors",
            "4",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["collected_stocks"] == 100
    assert payload["collected_sectors"] == 4
```

- [ ] **Step 2: Run the test and verify the CLI module is missing**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests\test_collector_cli.py -v
```

Expected: FAIL because `workbench.collector.main` does not exist.

- [ ] **Step 3: Implement explicit one-shot fake CLI arguments**

Create `backend/workbench/collector/main.py`:

```python
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.config import WorkbenchSettings
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="TDX market workbench collector")
    result.add_argument("--fake", action="store_true")
    result.add_argument("--once", action="store_true")
    result.add_argument("--date", required=True)
    result.add_argument("--minute", required=True)
    result.add_argument("--data-dir", type=Path, default=Path("../data"))
    result.add_argument("--stocks", type=int, default=5_500)
    result.add_argument("--sectors", type=int, default=400)
    result.add_argument("--members-per-sector", type=int, default=80)
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.fake or not args.once:
        parser().error("phase one requires --fake --once")
    trade_date = date.fromisoformat(args.date)
    settings = WorkbenchSettings(data_dir=args.data_dir)
    settings.ensure_directories()
    provider = FakeMarketProvider(args.stocks, args.sectors, args.members_per_sector)
    meta = MetaStore(settings.meta_db)
    meta.initialize()
    CatalogSyncService(provider, meta).sync()
    hot = HotStore(settings.hot_db_for(trade_date.isoformat()))
    hot.initialize()
    status = MinuteCollector(provider, meta, hot).collect(trade_date, args.minute)
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add and run the 5,500-stock capacity probe**

Create `backend/tools/benchmark_minute_batch.py`:

```python
from __future__ import annotations

import json
import tempfile
import time
from datetime import date
from pathlib import Path

from workbench.collector.catalog_sync import CatalogSyncService
from workbench.collector.minute_collector import MinuteCollector
from workbench.providers.fake import FakeMarketProvider
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tdx-capacity-") as raw:
        root = Path(raw)
        provider = FakeMarketProvider(5_500, 400, 80)
        meta = MetaStore(root / "meta.sqlite")
        meta.initialize()
        CatalogSyncService(provider, meta).sync()
        hot = HotStore(root / "2026-08-20.sqlite")
        hot.initialize()
        started = time.perf_counter()
        status = MinuteCollector(provider, meta, hot).collect(date(2026, 8, 20), "09:31")
        elapsed = time.perf_counter() - started
        result = {**status, "wall_seconds": round(elapsed, 3), "budget_seconds": 45.0}
        print(json.dumps(result, ensure_ascii=False))
        return 0 if elapsed <= 45.0 and status["coverage_pct"] == 100.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe tools\benchmark_minute_batch.py
```

Expected: exit code 0, `collected_stocks: 5500`, `collected_sectors: 400`, `coverage_pct: 100.0`, and `wall_seconds <= 45.0`.

- [ ] **Step 5: Run CLI/full tests and commit**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
git add backend/workbench/collector/main.py backend/tools/benchmark_minute_batch.py backend/tests/test_collector_cli.py
git commit -m "feat: add collector capacity probe"
```

### Task 11: Document and verify the phase-one vertical slice

**Files:**
- Modify: `README.md`
- Create: `docs/operations/development.md`

- [ ] **Step 1: Add exact development commands**

Update `README.md` with a “Market Workbench development” section linking the approved design and this plan. Create `docs/operations/development.md` with these commands:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m workbench.collector.main --fake --once --date 2026-08-20 --minute 09:31 --data-dir ..\data\workbench-dev --stocks 5500 --sectors 400
.\.venv\Scripts\python.exe -m uvicorn workbench.api.main:app --host 127.0.0.1 --port 8765
```

Document that phase one uses deterministic fake data and that real TDX collection is intentionally deferred to the next plan. Document the stock endpoint and sector endpoint with `date=2026-08-20&tiers=main,super,large` query examples.

- [ ] **Step 2: Run the complete backend verification**

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe tools\benchmark_minute_batch.py
.\.venv\Scripts\python.exe -m compileall -q workbench
```

Expected: all tests PASS, benchmark exits 0 under 45 seconds, compileall exits 0.

- [ ] **Step 3: Verify the unchanged frontend baseline**

```powershell
cd frontend
npm run build
```

Expected: production build succeeds. The existing chunk-size warning may remain; this phase does not alter frontend code.

- [ ] **Step 4: Inspect the branch before the final phase commit**

```powershell
git status --short
git diff --check
git log --oneline --decorate -12
```

Expected: only the intended README and operations document remain uncommitted; `git diff --check` prints no errors.

- [ ] **Step 5: Commit phase documentation**

```powershell
git add README.md docs/operations/development.md
git commit -m "docs: describe market data foundation"
```

## Phase-one exit criteria

The phase is complete only when all of the following are true:

1. The legacy `backend/app` service remains unchanged and importable.
2. The new collector writes one minute of 5,500 fake stock records and 400 aggregated sector records in at most 45 seconds.
3. Stock and sector APIs return the same `main`, `super`, and `large` tier shape with per-tier source and quality.
4. Repeating the same minute batch produces one row per entity, not duplicates.
5. `latest_complete_minute` advances only after stock, sector, and status rows commit together.
6. All pytest tests, Python compile checks, capacity probe, and frontend production build pass.
7. The branch is clean and every task has its own focused commit.
