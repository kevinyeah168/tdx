from __future__ import annotations

from datetime import date
from pathlib import Path

from workbench.domain import Membership, Sector, Security
from workbench.query.market import MarketQueryService
from workbench.query.sectors import SectorQueryService
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def seed_meta(store: MetaStore) -> None:
    store.replace_catalog(
        securities=[
            Security(symbol="SH600000", code="600000", name="浦发银行", market="SH"),
            Security(symbol="SZ000001", code="000001", name="平安银行", market="SZ"),
        ],
        sectors=[
            Sector(sector_id="881001", name="银行", sector_type="industry"),
            Sector(sector_id="885001", name="人工智能", sector_type="concept"),
        ],
        memberships=[
            Membership(sector_id="881001", symbol="SH600000"),
            Membership(sector_id="885001", symbol="SZ000001"),
        ],
        version="catalog-test",
        source="test",
    )


def test_market_overview_reports_catalog_and_latest_minute(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_meta(meta)
    hot = HotStore(tmp_path / "hot.sqlite")
    hot.initialize()

    overview = MarketQueryService(meta, hot).overview(date(2026, 8, 20))

    assert overview.security_count == 2
    assert overview.sector_count == 2
    assert overview.metadata.catalog_version == "catalog-test"


def test_search_returns_limited_matches(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_meta(meta)

    response = MarketQueryService(meta).search("600")

    assert response.query == "600"
    assert len(response.results) == 1
    assert response.results[0].symbol == "SH600000"


def test_sector_list_includes_member_counts(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_meta(meta)

    response = SectorQueryService(meta).list_sectors()

    assert len(response.items) == 2
    assert response.items[0].member_count == 1


def test_sector_list_supports_query_filter(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    seed_meta(meta)

    response = SectorQueryService(meta).list_sectors(query="银行", limit=10)

    assert len(response.items) == 1
    assert response.items[0].sector_id == "881001"
