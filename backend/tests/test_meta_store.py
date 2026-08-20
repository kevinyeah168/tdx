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
