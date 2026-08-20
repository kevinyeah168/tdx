from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

import pytest

import workbench.domain as domain_models
from workbench.domain import (
    Bar,
    DataEnvelope,
    OrderBook,
    ProviderCapabilities,
    QuoteSnapshot,
    Transaction,
)
from workbench.providers.base import (
    BarProvider,
    CapabilityProbe,
    CatalogProvider,
    MarketDataProvider,
    MinuteProvider,
    OrderBookProvider,
    QuoteProvider,
    TransactionProvider,
)
from workbench.providers.fake import FakeMarketProvider


class CompleteProvider(FakeMarketProvider):
    def quotes(self, symbols: Sequence[str]) -> DataEnvelope[list[QuoteSnapshot]]:
        raise NotImplementedError

    def transactions(
        self, symbol: str, trade_date: date
    ) -> DataEnvelope[list[Transaction]]:
        raise NotImplementedError

    def bars(
        self, symbol: str, period: domain_models.BarPeriod, count: int
    ) -> DataEnvelope[list[Bar]]:
        raise NotImplementedError

    def order_book(self, symbol: str) -> DataEnvelope[OrderBook]:
        raise NotImplementedError

    def probe_capabilities(self) -> DataEnvelope[ProviderCapabilities]:
        raise NotImplementedError


class WrongSignatureQuoteProvider:
    def quotes(self) -> int:
        return 0


def test_fake_provider_keeps_catalog_and_minute_contract_compatibility() -> None:
    provider = FakeMarketProvider(stock_count=1, sector_count=0, members_per_sector=0)

    assert isinstance(provider, CatalogProvider)
    assert isinstance(provider, MinuteProvider)
    assert isinstance(provider, MarketDataProvider)
    assert not isinstance(provider, QuoteProvider)
    assert not isinstance(provider, TransactionProvider)
    assert not isinstance(provider, BarProvider)
    assert not isinstance(provider, OrderBookProvider)
    assert not isinstance(provider, CapabilityProbe)


def test_full_provider_contract_is_split_by_data_responsibility() -> None:
    provider = CompleteProvider(stock_count=1, sector_count=0, members_per_sector=0)

    assert isinstance(provider, CatalogProvider)
    assert isinstance(provider, MinuteProvider)
    assert isinstance(provider, QuoteProvider)
    assert isinstance(provider, TransactionProvider)
    assert isinstance(provider, BarProvider)
    assert isinstance(provider, OrderBookProvider)
    assert isinstance(provider, CapabilityProbe)


def test_runtime_protocol_check_only_reports_method_presence() -> None:
    provider = WrongSignatureQuoteProvider()

    assert isinstance(provider, QuoteProvider)


def test_provider_protocol_signatures_are_checked_by_mypy() -> None:
    try:
        from mypy import api as mypy_api
    except ModuleNotFoundError:
        pytest.fail("mypy must be installed from backend/requirements-dev.txt")

    fixture_dir = Path(__file__).parent / "typing"
    common_arguments = [
        "--strict",
        "--follow-imports=silent",
        "--show-error-codes",
        "--no-error-summary",
        "--no-incremental",
    ]
    good_stdout, good_stderr, good_status = mypy_api.run(
        [str(fixture_dir / "provider_contract_good.py"), *common_arguments]
    )
    assert good_status == 0, good_stdout + good_stderr

    bad_stdout, bad_stderr, bad_status = mypy_api.run(
        [str(fixture_dir / "provider_contract_bad.py"), *common_arguments]
    )
    assert bad_status == 1
    assert "Incompatible types in assignment" in bad_stdout
    assert "QuoteProvider" in bad_stdout
    assert bad_stderr == ""
