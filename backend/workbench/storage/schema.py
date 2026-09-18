import sqlite3


def configure_hot_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=15000")


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
    version TEXT NOT NULL,
    synced_at TEXT,
    source TEXT NOT NULL DEFAULT 'unknown',
    stale INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS sector_group (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sector_group_member (
    group_id TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, sector_id),
    FOREIGN KEY (group_id) REFERENCES sector_group(group_id) ON DELETE CASCADE
);
"""

HOT_SCHEMA = """
PRAGMA journal_mode=WAL;

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
    catalog_version TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS stock_gray_minute (
    trade_date TEXT NOT NULL,
    minute TEXT NOT NULL,
    symbol TEXT NOT NULL,
    code TEXT NOT NULL,
    open_cum REAL NOT NULL,
    dark_cum REAL NOT NULL,
    total_cum REAL NOT NULL,
    observed_at TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (trade_date, minute, symbol)
);

CREATE INDEX IF NOT EXISTS idx_stock_gray_series
ON stock_gray_minute(trade_date, symbol, minute);

CREATE TABLE IF NOT EXISTS sector_gray_minute (
    trade_date TEXT NOT NULL,
    minute TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    member_count INTEGER NOT NULL,
    gray_covered_count INTEGER NOT NULL,
    open_cum REAL NOT NULL,
    dark_cum REAL NOT NULL,
    total_cum REAL NOT NULL,
    observed_at TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source TEXT NOT NULL,
    quality TEXT NOT NULL,
    PRIMARY KEY (trade_date, minute, sector_id)
);

CREATE INDEX IF NOT EXISTS idx_sector_gray_series
ON sector_gray_minute(trade_date, sector_id, minute);

CREATE TABLE IF NOT EXISTS market_scope_minute (
    trade_date TEXT NOT NULL,
    minute TEXT NOT NULL,
    scope TEXT NOT NULL,
    change_pct REAL NOT NULL,
    main_delta REAL NOT NULL,
    main_cum REAL NOT NULL,
    tier_meta_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    PRIMARY KEY (trade_date, minute, scope)
);

CREATE INDEX IF NOT EXISTS idx_market_scope_series
ON market_scope_minute(trade_date, scope, minute);
"""
