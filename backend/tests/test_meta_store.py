import sqlite3
from pathlib import Path

import pytest

import workbench.storage.meta_store as meta_store_module
from workbench.storage.schema import HOT_SCHEMA, configure_hot_connection
from workbench.domain import Membership, Sector, Security
from workbench.storage.meta_store import MetaStore


def test_configure_hot_connection_applies_connection_scoped_pragmas(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "hot.sqlite")
    try:
        configure_hot_connection(connection)

        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()


def test_meta_store_initialization_enables_wal(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()

    connection = sqlite3.connect(tmp_path / "meta.sqlite")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()


def test_hot_schema_does_not_contain_connection_scoped_synchronous_pragma() -> None:
    assert "PRAGMA synchronous=NORMAL" not in HOT_SCHEMA


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


def test_catalog_snapshot_returns_memberships_count_and_version_together(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    store.replace_catalog(
        securities=[Security(symbol="SH600000", code="600000", name="Stock", market="SH")],
        sectors=[Sector(sector_id="881001", name="Sector", sector_type="industry")],
        memberships=[Membership(sector_id="881001", symbol="SH600000")],
        version="catalog-v1",
    )

    snapshot = store.catalog_snapshot()

    assert snapshot.memberships == (Membership(sector_id="881001", symbol="SH600000"),)
    assert snapshot.sector_count == 1
    assert snapshot.catalog_version == "catalog-v1"


def test_retention_defaults_to_thirty_and_can_change(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()

    assert store.retention_days() == 30
    store.set_retention_days(60)
    assert store.retention_days() == 60


@pytest.mark.parametrize("invalid_days", [60.0, True, False, "60", 0, 2501])
def test_retention_rejects_invalid_values_without_changing_the_saved_value(
    tmp_path: Path, invalid_days: object
) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    store.set_retention_days(60)

    with pytest.raises(ValueError):
        store.set_retention_days(invalid_days)  # type: ignore[arg-type]

    assert store.retention_days() == 60


def test_replace_catalog_rolls_back_all_state_on_membership_foreign_key_failure(
    tmp_path: Path,
) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    store.replace_catalog(
        securities=[Security(symbol="SH600000", code="600000", name="浦发银行", market="SH")],
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=[Membership(sector_id="881001", symbol="SH600000")],
        version="2026-08-20",
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.replace_catalog(
            securities=[Security(symbol="SZ000001", code="000001", name="平安银行", market="SZ")],
            sectors=[Sector(sector_id="881002", name="保险", sector_type="industry")],
            memberships=[Membership(sector_id="881002", symbol="SH999999")],
            version="2026-08-21",
        )

    assert store.security_count() == 1
    assert store.sector_count() == 1
    assert store.memberships_for("881001") == ["SH600000"]
    assert store.catalog_version() == "2026-08-20"


def test_fresh_meta_store_connection_enforces_foreign_keys(tmp_path: Path) -> None:
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()

    connection = store.connect()
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO sector_membership VALUES(?, ?)", ("881001", "SH600000")
            )
    finally:
        connection.close()


def test_meta_store_methods_close_connections_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TrackingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection
            self.closed = False

        def __enter__(self) -> "TrackingConnection":
            self.connection.__enter__()
            return self

        def __exit__(self, *args: object) -> bool | None:
            return self.connection.__exit__(*args)

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

        def close(self) -> None:
            self.closed = True
            self.connection.close()

    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    original_connect = sqlite3.connect
    tracked_connections: list[TrackingConnection] = []

    def track_connection(path: str | Path) -> TrackingConnection:
        connection = TrackingConnection(original_connect(path))
        tracked_connections.append(connection)
        return connection

    monkeypatch.setattr(meta_store_module.sqlite3, "connect", track_connection)
    try:
        assert store.security_count() == 0
        assert tracked_connections[0].closed
    finally:
        for connection in tracked_connections:
            if not connection.closed:
                connection.close()
