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
