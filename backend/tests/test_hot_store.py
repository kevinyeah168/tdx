from datetime import date, datetime
from pathlib import Path
import time
import threading

import sqlite3
from copy import deepcopy

import pytest

import workbench.storage.hot_store as hot_store_module
from workbench.domain import CollectionStatus, DataQuality, FundFlow, SectorMinute, StockMinute, TierPoint
from workbench.storage.hot_store import HotStore
from workbench.storage.schema import HOT_SCHEMA


def stock_record(
    close: float, *, symbol: str = "SH600000", batch_id: str = "2026-08-20T09:31"
) -> StockMinute:
    return StockMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        symbol=symbol,
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
        batch_id=batch_id,
    )


def sector_record(*, sector_id: str = "881001", batch_id: str = "2026-08-20T09:31") -> SectorMinute:
    def tier(delta: float, cumulative: float, source: str) -> TierPoint:
        return TierPoint(
            delta=delta,
            cumulative=cumulative,
            source=source,
            quality=DataQuality.AGGREGATED,
        )

    return SectorMinute(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        sector_id=sector_id,
        change_pct=1.5,
        member_count=2,
        funds=FundFlow(
            main=tier(99.0, 199.0, "main_sum"),
            super=tier(30.0, 100.0, "super_sum"),
            large=tier(10.0, 40.0, "large_sum"),
            medium=tier(5.0, 20.0, "medium_sum"),
            small=tier(-2.0, -5.0, "small_sum"),
        ),
        observed_at=datetime(2026, 8, 20, 9, 31, 5),
        batch_id=batch_id,
    )


def batch_status(*, status: str = "complete") -> CollectionStatus:
    return CollectionStatus(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        batch_id="2026-08-20T09:31",
        catalog_version="fake-v1",
        expected_stocks=1,
        collected_stocks=1,
        expected_sectors=1,
        collected_sectors=1,
        duration_ms=0,
        coverage_pct=100.0,
        status=status,
        error_summary="",
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


def test_complete_batch_round_trips_sector_tiers_and_provenance(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()

    store.write_complete_batch(
        [stock_record(10.0)], [sector_record()], batch_status(), started_at=0.0
    )

    rows = store.sector_fund_series("2026-08-20", "881001")
    assert len(rows) == 1
    assert rows[0]["main_delta"] == 99.0
    assert rows[0]["super_cum"] == 100.0
    assert rows[0]["large_cum"] == 40.0
    assert rows[0]["tier_meta"] == {
        "main": {"source": "main_sum", "quality": "aggregated"},
        "super": {"source": "super_sum", "quality": "aggregated"},
        "large": {"source": "large_sum", "quality": "aggregated"},
        "medium": {"source": "medium_sum", "quality": "aggregated"},
        "small": {"source": "small_sum", "quality": "aggregated"},
    }


def test_complete_batch_rolls_back_all_rows_when_status_insert_fails(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    with store._session() as connection:
        connection.execute(
            "CREATE TRIGGER fail_status BEFORE INSERT ON collection_status "
            "BEGIN SELECT RAISE(ABORT, 'status failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError):
        store.write_complete_batch(
            [stock_record(10.0)], [sector_record()], batch_status(), started_at=0.0
        )

    assert store.stock_fund_series("2026-08-20", "SH600000") == []
    assert store.sector_fund_series("2026-08-20", "881001") == []
    assert store.latest_complete_minute("2026-08-20") is None


def test_complete_batch_is_idempotent_and_does_not_mutate_status(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    status = batch_status()
    original = deepcopy(status)

    store.write_complete_batch([stock_record(10.0)], [sector_record()], status, started_at=0.0)
    store.write_complete_batch([stock_record(10.2)], [sector_record()], status, started_at=0.0)

    assert status == original
    assert len(store.stock_fund_series("2026-08-20", "SH600000")) == 1
    assert len(store.sector_fund_series("2026-08-20", "881001")) == 1


def test_readonly_connect_does_not_create_parent_directories(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing" / "hot.sqlite"

    with pytest.raises(sqlite3.OperationalError):
        HotStore(missing_path).connect(readonly=True)

    assert not missing_path.parent.exists()


def test_initialize_migrates_legacy_collection_status_catalog_provenance(tmp_path: Path) -> None:
    path = tmp_path / "2026-08-20.sqlite"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            HOT_SCHEMA.replace("    catalog_version TEXT NOT NULL,\n", "")
        )
        connection.execute(
            "INSERT INTO collection_status VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-08-20", "09:30", "legacy-batch", 1, 1, 0, 0, 12, 100.0, "complete", ""),
        )
        connection.commit()
    finally:
        connection.close()

    store = HotStore(path)
    store.initialize()
    store.initialize()

    with store._session(readonly=True) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(collection_status)")}
        legacy_row = connection.execute(
            "SELECT catalog_version FROM collection_status WHERE minute='09:30'"
        ).fetchone()
    assert "catalog_version" in columns
    assert legacy_row[0] == "legacy-unknown"
    assert store.latest_complete_minute("2026-08-20") == "09:30"

    store.write_complete_batch(
        [stock_record(10.0)], [sector_record()], batch_status(), started_at=time.perf_counter()
    )

    assert store.latest_complete_minute("2026-08-20") == "09:31"
    assert len(store.stock_fund_series("2026-08-20", "SH600000")) == 1


def test_concurrent_initializers_serialize_legacy_catalog_provenance_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "2026-08-20.sqlite"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            HOT_SCHEMA.replace("    catalog_version TEXT NOT NULL,\n", "")
        )
        connection.execute(
            "INSERT INTO collection_status VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-08-20", "09:30", "legacy-batch", 1, 1, 0, 0, 12, 100.0, "complete", ""),
        )
        connection.commit()
    finally:
        connection.close()

    barrier = threading.Barrier(2)
    original_connect = HotStore.connect

    class BarrierConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def __enter__(self) -> "BarrierConnection":
            self.connection.__enter__()
            return self

        def __exit__(self, *args: object) -> bool | None:
            return self.connection.__exit__(*args)

        def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:
            if sql == "BEGIN IMMEDIATE":
                barrier.wait(timeout=5)
            return self.connection.execute(sql, parameters)

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

    def connect_with_barrier(
        self: HotStore, *, readonly: bool = False, immutable: bool | None = None
    ) -> BarrierConnection:
        return BarrierConnection(original_connect(self, readonly=readonly, immutable=immutable))

    monkeypatch.setattr(HotStore, "connect", connect_with_barrier)
    errors: list[BaseException] = []

    def initialize(store: HotStore) -> None:
        try:
            store.initialize()
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=initialize, args=(HotStore(path),)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    store = HotStore(path)
    with store._session(readonly=True) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(collection_status)")]
        legacy_row = connection.execute(
            "SELECT catalog_version FROM collection_status WHERE minute='09:30'"
        ).fetchone()
    assert columns.count("catalog_version") == 1
    assert legacy_row[0] == "legacy-unknown"

    store.write_complete_batch(
        [stock_record(10.0)], [sector_record()], batch_status(), started_at=time.perf_counter()
    )
    assert store.latest_complete_minute("2026-08-20") == "09:31"


def test_complete_batch_duration_includes_stock_write_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    original_params = hot_store_module._stock_params

    def delayed_params(record: StockMinute) -> dict[str, object]:
        time.sleep(0.02)
        return original_params(record)

    monkeypatch.setattr(hot_store_module, "_stock_params", delayed_params)
    result = store.write_complete_batch(
        [stock_record(10.0)], [sector_record()], batch_status(), started_at=time.perf_counter()
    )

    assert result["duration_ms"] >= 20


@pytest.mark.parametrize(
    ("stocks", "sectors", "match"),
    [
        ([stock_record(10.0), stock_record(10.1)], [sector_record()], "duplicate stock symbols"),
        ([stock_record(10.0)], [sector_record(), sector_record()], "duplicate sector IDs"),
        ([stock_record(10.0, batch_id="wrong")], [sector_record()], "batch_id"),
        ([stock_record(10.0)], [sector_record(batch_id="wrong")], "batch_id"),
    ],
)
def test_complete_batch_rejects_invalid_record_identity_without_persistence(
    tmp_path: Path,
    stocks: list[StockMinute],
    sectors: list[SectorMinute],
    match: str,
) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()

    with pytest.raises(ValueError, match=match):
        store.write_complete_batch(stocks, sectors, batch_status(), started_at=time.perf_counter())

    assert store.stock_fund_series("2026-08-20", "SH600000") == []
    assert store.sector_fund_series("2026-08-20", "881001") == []


def test_complete_batch_rejects_status_counts_that_do_not_match_records(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    status = batch_status().model_copy(
        update={"expected_stocks": 2, "collected_stocks": 2, "coverage_pct": 100.0}
    )

    with pytest.raises(ValueError, match="collected_stocks must match stock records"):
        store.write_complete_batch(
            [stock_record(10.0)], [sector_record()], status, started_at=time.perf_counter()
        )

    assert store.stock_fund_series("2026-08-20", "SH600000") == []


def test_reduced_retry_replaces_the_entire_minute_snapshot(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    full_status = batch_status().model_copy(
        update={"expected_stocks": 2, "collected_stocks": 2, "expected_sectors": 2, "collected_sectors": 2}
    )
    store.write_complete_batch(
        [stock_record(10.0), stock_record(10.1, symbol="SH600001")],
        [sector_record(), sector_record(sector_id="881002")],
        full_status,
        started_at=time.perf_counter(),
    )

    store.write_complete_batch(
        [stock_record(10.2)], [sector_record()], batch_status(), started_at=time.perf_counter()
    )

    assert len(store.stock_fund_series("2026-08-20", "SH600000")) == 1
    assert store.stock_fund_series("2026-08-20", "SH600001") == []
    assert len(store.sector_fund_series("2026-08-20", "881001")) == 1
    assert store.sector_fund_series("2026-08-20", "881002") == []


def test_failed_retry_retains_the_previously_committed_snapshot_and_status(tmp_path: Path) -> None:
    store = HotStore(tmp_path / "2026-08-20.sqlite")
    store.initialize()
    store.write_complete_batch(
        [stock_record(10.0)], [sector_record()], batch_status(), started_at=time.perf_counter()
    )
    with store._session() as connection:
        connection.execute(
            "CREATE TRIGGER fail_status BEFORE INSERT ON collection_status "
            "BEGIN SELECT RAISE(ABORT, 'status failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError):
        store.write_complete_batch(
            [],
            [],
            batch_status().model_copy(
                update={"collected_stocks": 0, "collected_sectors": 0, "coverage_pct": 0.0, "status": "partial"}
            ),
            started_at=time.perf_counter(),
        )

    assert len(store.stock_fund_series("2026-08-20", "SH600000")) == 1
    assert len(store.sector_fund_series("2026-08-20", "881001")) == 1
    with store._session(readonly=True) as connection:
        assert connection.execute("SELECT status FROM collection_status").fetchone()[0] == "complete"
