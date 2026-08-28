from __future__ import annotations

from pathlib import Path

import pytest

from workbench.providers.tdx.catalog import TdxCatalogLoader, build_catalog_from_rows
from workbench.providers.tdx.symbols import is_a_share, parse_symbol, to_symbol
from workbench.storage.meta_store import MetaStore


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


def test_symbol_mapping_covers_sh_sz_bj() -> None:
    assert to_symbol("SH", "600000") == "SH600000"
    assert to_symbol("SZ", "000001") == "SZ000001"
    assert to_symbol("BJ", "920001") == "BJ920001"
    assert parse_symbol("SH600000") == ("SH", "600000")


def test_a_share_filter_excludes_index_and_etf() -> None:
    assert is_a_share("SH", "600000")
    assert not is_a_share("SH", "000001")
    assert is_a_share("SZ", "000001")
    assert not is_a_share("SZ", "159915")


def test_fixture_catalog_deduplicates_boards_and_memberships() -> None:
    catalog = TdxCatalogLoader.from_fixture_dir(FIXTURE_DIR).load().catalog

    assert len(catalog.securities) == 3
    assert {security.market for security in catalog.securities} == {"SH", "SZ", "BJ"}
    assert len(catalog.sectors) == 2
    assert len(catalog.memberships) == 2
    assert {membership.symbol for membership in catalog.memberships} == {"SH600000", "SZ000001"}
    assert catalog.version.startswith("catalog-")


def test_meta_store_persists_catalog_sync_metadata(tmp_path: Path) -> None:
    loader = TdxCatalogLoader.from_fixture_dir(FIXTURE_DIR)
    catalog = loader.load().catalog
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    store.replace_catalog(
        securities=catalog.securities,
        sectors=catalog.sectors,
        memberships=catalog.memberships,
        version=catalog.version,
        synced_at="2026-08-21T09:30:00",
        source="tdx.fixture",
        stale=False,
    )

    snapshot = store.catalog_snapshot()

    assert snapshot.catalog_version == catalog.version
    assert snapshot.synced_at == "2026-08-21T09:30:00"
    assert snapshot.source == "tdx.fixture"
    assert snapshot.stale is False


def test_stale_sync_keeps_previous_catalog(tmp_path: Path) -> None:
    loader = TdxCatalogLoader.from_fixture_dir(FIXTURE_DIR)
    catalog = loader.load().catalog
    store = MetaStore(tmp_path / "meta.sqlite")
    store.initialize()
    store.replace_catalog(
        securities=catalog.securities,
        sectors=catalog.sectors,
        memberships=catalog.memberships,
        version=catalog.version,
        source="tdx.fixture",
    )
    store.mark_catalog_stale(error_summary="network failed", source="tdx.network")

    snapshot = store.catalog_snapshot()

    assert snapshot.stale is True
    assert snapshot.error_summary == "network failed"
    assert store.security_count() == 3


def test_build_catalog_from_rows_hashes_version_deterministically() -> None:
    rows = [
        {"market": "SH", "code": "600000", "name": "浦发银行"},
        {"market": "SZ", "code": "000001", "name": "平安银行"},
    ]
    first = build_catalog_from_rows(
        security_rows=rows,
        board_rows=[{"sector_id": "881001", "name": "银行", "sector_type": "industry"}],
        member_rows=[{"sector_id": "881001", "symbol": "SH600000"}],
        source="fixture",
    )
    second = build_catalog_from_rows(
        security_rows=list(reversed(rows)),
        board_rows=[{"sector_id": "881001", "name": "银行", "sector_type": "industry"}],
        member_rows=[{"sector_id": "881001", "symbol": "SH600000"}],
        source="fixture",
    )

    assert first.version == second.version
