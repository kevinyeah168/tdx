from datetime import date

import pytest
from pydantic import ValidationError

from workbench.domain import Membership, Security, Sector
from workbench.providers.base import MarketCatalog
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


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("stock_count", True),
        ("stock_count", 1.0),
        ("sector_count", True),
        ("sector_count", 1.0),
        ("members_per_sector", True),
        ("members_per_sector", 1.0),
    ],
)
def test_fake_provider_rejects_non_integer_sizes(argument: str, value: object) -> None:
    arguments: dict[str, object] = {
        "stock_count": 2,
        "sector_count": 1,
        "members_per_sector": 1,
    }
    arguments[argument] = value

    with pytest.raises(ValueError):
        FakeMarketProvider(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "arguments",
    [
        {"stock_count": 0, "sector_count": 0, "members_per_sector": 0},
        {"stock_count": -1, "sector_count": 0, "members_per_sector": 0},
        {"stock_count": 1, "sector_count": -1, "members_per_sector": 0},
        {"stock_count": 1, "sector_count": 0, "members_per_sector": -1},
        {"stock_count": 2, "sector_count": 1, "members_per_sector": 3},
    ],
)
def test_fake_provider_rejects_invalid_size_bounds(arguments: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        FakeMarketProvider(**arguments)


def test_fake_provider_allows_empty_sector_catalog() -> None:
    provider = FakeMarketProvider(stock_count=1, sector_count=0, members_per_sector=0)

    assert provider.catalog().sectors == []


def test_fake_provider_catalog_does_not_leak_security_mutations() -> None:
    provider = FakeMarketProvider(stock_count=2, sector_count=1, members_per_sector=1)
    catalog = provider.catalog()
    catalog.securities[0].symbol = "MUTATED"
    catalog.securities[0].name = "Mutated"

    fresh_catalog = provider.catalog()
    batch = provider.minute_batch(date(2026, 8, 20), "09:31")

    assert fresh_catalog.securities[0].symbol == "SH600000"
    assert fresh_catalog.securities[0].name != "Mutated"
    assert batch.stocks[0].symbol == "SH600000"


def market_catalog(**overrides: object) -> MarketCatalog:
    values: dict[str, object] = {
        "securities": [Security(symbol="SH600000", code="600000", name="Stock", market="SH")],
        "sectors": [Sector(sector_id="880000", name="Sector", sector_type="industry")],
        "memberships": [Membership(sector_id="880000", symbol="SH600000")],
        "version": "v1",
    }
    values.update(overrides)
    return MarketCatalog(**values)


def test_market_catalog_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        market_catalog(unknown=True)


def test_market_catalog_normalizes_and_requires_a_version() -> None:
    assert market_catalog(version=" v1\t").version == "v1"

    with pytest.raises(ValidationError):
        market_catalog(version=" \t")


def test_market_catalog_rejects_duplicate_security_symbols() -> None:
    with pytest.raises(ValidationError):
        market_catalog(
            securities=[
                Security(symbol="SH600000", code="600000", name="One", market="SH"),
                Security(symbol="SH600000", code="000001", name="Two", market="SZ"),
            ]
        )


def test_market_catalog_rejects_duplicate_sector_ids() -> None:
    with pytest.raises(ValidationError):
        market_catalog(
            sectors=[
                Sector(sector_id="880000", name="One", sector_type="industry"),
                Sector(sector_id="880000", name="Two", sector_type="concept"),
            ]
        )


def test_market_catalog_rejects_duplicate_membership_pairs() -> None:
    membership = Membership(sector_id="880000", symbol="SH600000")

    with pytest.raises(ValidationError):
        market_catalog(memberships=[membership, membership])


def test_market_catalog_requires_membership_security_reference() -> None:
    with pytest.raises(ValidationError):
        market_catalog(memberships=[Membership(sector_id="880000", symbol="SZ000001")])


def test_market_catalog_requires_membership_sector_reference() -> None:
    with pytest.raises(ValidationError):
        market_catalog(memberships=[Membership(sector_id="880001", symbol="SH600000")])
