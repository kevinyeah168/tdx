from __future__ import annotations

from datetime import date
from pathlib import Path

from workbench.config import WorkbenchSettings
from workbench.providers.tdx.provider import TdxMarketProvider


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


def test_fixture_provider_builds_catalog_and_minute_batch() -> None:
    provider = TdxMarketProvider(WorkbenchSettings(), fixture_dir=FIXTURE_DIR)
    catalog = provider.catalog()
    batch = provider.minute_batch(date(2026, 8, 20), "09:31")

    assert len(catalog.securities) == 3
    assert len(catalog.sectors) == 2
    assert batch.expected_stocks == 3
    assert len(batch.stocks) == 3
    assert batch.trade_date == date(2026, 8, 20)
    assert batch.minute == "09:31"


def test_fixture_provider_returns_daily_bars() -> None:
    provider = TdxMarketProvider(WorkbenchSettings(), fixture_dir=FIXTURE_DIR)
    envelope = provider.bars("SH600000", "day", 2)

    assert envelope.quality.value == "official"
    assert envelope.data is not None
    assert len(envelope.data) == 2
    assert envelope.data[-1].close == 12.7
