from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from easy_tdx import KlineCategory, Market
from easy_tdx.codec.bitmap import Fields, normalize_fields
import pandas as pd
import pytest

from workbench.providers.tdx import probe as tdx_probe
from workbench.providers.tdx.probe import (
    enhanced_handicap_plan,
    probe_tdx_capabilities,
)
from workbench.providers.tdx.probe_models import CAPABILITY_NAMES, TdxCapabilityReport
from workbench.providers.tdx.probe_worker import InlineTestSourceExecutor


CAPTURED_AT = datetime(
    2026,
    8,
    21,
    12,
    0,
    tzinfo=timezone(timedelta(hours=8)),
)


class StepClock:
    def __init__(self, step: float = 0.0001234) -> None:
        self.value = -step
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class FakePool:
    def __init__(self, client: object) -> None:
        self.client = client

    def execute(self, operation: Callable[[Any], Any]) -> Any:
        return operation(self.client)


class FakeNormalProbeClient:
    def __init__(
        self,
        failures: set[str] | None = None,
        *,
        catalog_hook: Callable[[], None] | None = None,
    ) -> None:
        self.failures = failures or set()
        self.catalog_hook = catalog_hook
        self.full_list_calls: list[object] = []
        self.stock_requests: list[tuple[str, Market, str]] = []

    def _fail(self, method: str) -> None:
        if method in self.failures:
            raise RuntimeError(f"{method} unavailable")

    def get_security_list_all(self, pages: int | str = "all") -> pd.DataFrame:
        self._fail("get_security_list_all")
        self.full_list_calls.append(pages)
        if self.catalog_hook is not None:
            self.catalog_hook()
        return pd.DataFrame(
            [
                {"market": Market.SH, "code": "600000", "name": "浦发银行"},
                {"market": Market.SH, "code": "688001", "name": "科创样本"},
                {"market": Market.SZ, "code": "000001", "name": "平安银行"},
                {"market": Market.SZ, "code": "300001", "name": "创业样本"},
                {"market": Market.BJ, "code": "430047", "name": "北交样本一"},
                {"market": Market.BJ, "code": "830001", "name": "北交样本二"},
            ]
        )

    def get_security_quotes(
        self, stocks: list[tuple[Market, str]]
    ) -> pd.DataFrame:
        self._fail("get_security_quotes")
        market, code = stocks[0]
        self.stock_requests.append(("quotes", market, code))
        row: dict[str, object] = {
            "market": market,
            "code": code,
            "price": 12.34,
            "pre_close": 12.20,
            "open": 12.10,
            "high": 12.50,
            "low": 12.00,
            "close": 12.34,
            "vol": 1000.0,
            "amount": 12340.0,
        }
        for level in range(1, 6):
            row[f"bid{level}"] = 12.30 - level / 100
            row[f"bid_vol{level}"] = 1000 + level
            row[f"ask{level}"] = 12.34 + level / 100
            row[f"ask_vol{level}"] = 1100 + level
        return pd.DataFrame([row])

    def get_transaction_data(
        self,
        market: Market,
        code: str,
        start: int,
        count: int = 800,
    ) -> pd.DataFrame:
        self._fail("get_transaction_data")
        self.stock_requests.append(("transactions", market, code))
        assert start == 0
        assert count == 3
        return pd.DataFrame(
            [{"time": "14:59", "price": 12.34, "vol": 2, "num": 1}]
        )

    def get_minute_time_data(self, market: Market, code: str) -> pd.DataFrame:
        self._fail("get_minute_time_data")
        self.stock_requests.append(("minute_data", market, code))
        return pd.DataFrame(
            [{"datetime": "2026-08-21T14:59:00+08:00", "price": 12.34, "vol": 100}]
        )

    def get_security_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
    ) -> pd.DataFrame:
        self._fail("get_security_bars")
        self.stock_requests.append(("bars", market, code))
        assert category is KlineCategory.DAY
        assert start == 0
        assert count == 3
        return pd.DataFrame(
            [
                {
                    "datetime": "2026-08-21",
                    "open": 12.10,
                    "high": 12.50,
                    "low": 12.00,
                    "close": 12.34,
                    "vol": 1000.0,
                    "amount": 12340.0,
                }
            ]
        )


class FakeEnhancedProbeClient:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.board_member_requests: list[str] = []
        self.stock_requests: list[tuple[str, int, str]] = []
        self.quote_fields: list[object] = []

    def _fail(self, method: str) -> None:
        if method in self.failures:
            raise RuntimeError(f"{method} unavailable")

    def get_board_list(self, *, board_type: object, count: int) -> pd.DataFrame:
        self._fail("get_board_list")
        assert getattr(board_type, "name", None) == "HY"
        assert count == 8
        return pd.DataFrame(
            [
                {"market": 1, "code": "881777", "name": "探针行业一"},
                {"market": 1, "code": "881778", "name": "探针行业二"},
            ]
        )

    def get_board_members(self, board_symbol: str, *, count: int) -> pd.DataFrame:
        self._fail("get_board_members")
        self.board_member_requests.append(board_symbol)
        assert count == 3
        return pd.DataFrame(
            [{"market": 1, "code": "600000", "name": "浦发银行", "close": 12.34}]
        )

    def get_capital_flow(self, market: int, code: str) -> pd.DataFrame:
        self._fail("get_capital_flow")
        self.stock_requests.append(("official_funds", market, code))
        return pd.DataFrame(
            [
                {
                    "date": "",
                    "main_in": 10.0,
                    "main_out": 8.0,
                    "main_net": 2.0,
                    "small_in": 4.0,
                    "small_out": 5.0,
                    "small_net": -1.0,
                    "mid_in": 3.0,
                    "mid_out": 2.0,
                    "mid_net": 1.0,
                    "large_in": 3.0,
                    "large_out": 1.0,
                    "large_net": 2.0,
                }
            ]
        )

    def get_stock_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: object = None,
    ) -> pd.DataFrame:
        self._fail("get_stock_quotes")
        market, code = stocks[0]
        self.stock_requests.append(("stock_quotes", market, code))
        self.quote_fields.append(fields)
        selected = list(normalize_fields(cast(Fields, fields)))
        if any(bit.value == 17 for bit in selected):
            values: dict[str, object] = {}
            for bit in selected:
                is_volume = "volume" in bit.field_name or "count" in bit.field_name
                values[bit.field_name] = 100 if is_volume else 12.34
            return pd.DataFrame(
                [{"market": market, "code": code, "name": "浦发银行", **values}]
            )
        return pd.DataFrame(
            [
                {
                    "market": market,
                    "code": code,
                    "name": "浦发银行",
                    "pre_close": 12.20,
                    "open": 12.10,
                    "high": 12.50,
                    "low": 12.00,
                    "close": 12.34,
                    "vol": 1000,
                    "amount": 12340.0,
                }
            ]
        )

    def get_stock_kline(
        self,
        market: int,
        code: str,
        period: object,
        start: int,
        count: int,
    ) -> pd.DataFrame:
        self._fail("get_stock_kline")
        self.stock_requests.append(("stock_kline", market, code))
        assert getattr(period, "name", None) == "DAILY"
        assert start == 0
        assert count == 3
        return pd.DataFrame(
            [
                {
                    "datetime": "2026-08-21",
                    "open": 12.10,
                    "high": 12.50,
                    "low": 12.00,
                    "close": 12.34,
                    "vol": 1000.0,
                    "amount": 12340.0,
                }
            ]
        )


def run_probe(
    *,
    normal: FakeNormalProbeClient | None = None,
    enhanced: FakeEnhancedProbeClient | None = None,
    clock: Callable[[], float] | None = None,
    overall_hard_deadline_seconds: float = 120.0,
    capability_hard_deadline_seconds: float = 20.0,
) -> TdxCapabilityReport:
    return probe_tdx_capabilities(
        source_executor=InlineTestSourceExecutor(
            FakePool(normal or FakeNormalProbeClient()),
            FakePool(enhanced or FakeEnhancedProbeClient()),
        ),
        clock=clock or StepClock(),
        captured_at=CAPTURED_AT,
        easy_tdx_version="1.20.7",
        overall_hard_deadline_seconds=overall_hard_deadline_seconds,
        capability_hard_deadline_seconds=capability_hard_deadline_seconds,
    )


def test_probe_uses_full_catalog_and_returns_strict_report_with_discovered_board() -> None:
    normal = FakeNormalProbeClient()
    enhanced = FakeEnhancedProbeClient()

    report = run_probe(normal=normal, enhanced=enhanced)

    assert len(normal.full_list_calls) == 1
    assert isinstance(normal.full_list_calls[0], int)
    assert report.manifest.sample_symbol == "SH600000"
    assert report.manifest.discovered_board is not None
    assert report.manifest.discovered_board.id == "881777"
    assert report.manifest.discovered_board.name == "探针行业一"
    assert enhanced.board_member_requests == ["881777"]
    assert set(report.capabilities.model_dump()) == set(CAPABILITY_NAMES)
    assert set(report.manifest.source_outcomes.model_dump()) == set(CAPABILITY_NAMES)
    assert all(
        market is Market.SH and code == "600000"
        for _, market, code in normal.stock_requests
    )
    assert all(
        market == int(Market.SH) and code == "600000"
        for _, market, code in enhanced.stock_requests
    )


def test_composite_fallback_retains_each_normal_and_enhanced_source_outcome() -> None:
    normal = FakeNormalProbeClient({"get_security_quotes", "get_security_bars"})

    report = run_probe(normal=normal)

    assert report.capabilities.quotes.available is True
    assert report.capabilities.quotes.source == "tdx.enhanced.quotes"
    quote_outcomes = report.manifest.source_outcomes.quotes
    assert [outcome.source for outcome in quote_outcomes] == [
        "tdx.normal.quotes",
        "tdx.enhanced.quotes",
    ]
    assert [outcome.status for outcome in quote_outcomes] == ["failed", "succeeded"]
    assert quote_outcomes[0].error is not None
    assert quote_outcomes[1].evidence

    assert report.capabilities.bars.available is True
    bar_outcomes = report.manifest.source_outcomes.bars
    assert [outcome.status for outcome in bar_outcomes] == ["failed", "succeeded"]

    order_book_outcomes = report.manifest.source_outcomes.order_book
    assert [outcome.source for outcome in order_book_outcomes] == [
        "tdx.normal.order-book",
        "tdx.enhanced.order-book",
    ]
    assert order_book_outcomes[0].status == "failed"
    if enhanced_handicap_plan().levels == 2:
        assert order_book_outcomes[1].status == "failed"
        assert {"bid2_volume", "ask2_volume"} <= set(
            order_book_outcomes[1].evidence
        )
        assert "LocalClientCapabilityLimitation" in (
            order_book_outcomes[1].error or ""
        )


def test_normal_five_level_order_book_can_make_aggregate_available() -> None:
    report = run_probe()

    assert report.capabilities.order_book.available is True
    assert report.capabilities.order_book.source == "tdx.normal.order-book"
    assert report.manifest.source_outcomes.order_book[0].status == "succeeded"
    assert "bid5_price" in report.manifest.source_outcomes.order_book[0].evidence


def test_semantically_wrong_quote_source_fails_while_other_source_is_attempted() -> None:
    class WrongSymbolNormal(FakeNormalProbeClient):
        def get_security_quotes(
            self, stocks: list[tuple[Market, str]]
        ) -> pd.DataFrame:
            response = super().get_security_quotes(stocks)
            response.loc[0, "code"] = "000001"
            return response

    report = run_probe(
        normal=WrongSymbolNormal(),
        enhanced=FakeEnhancedProbeClient({"get_stock_quotes"}),
    )

    assert report.capabilities.quotes.available is False
    assert [outcome.status for outcome in report.manifest.source_outcomes.quotes] == [
        "failed",
        "failed",
    ]
    assert "symbol" in (report.manifest.source_outcomes.quotes[0].error or "").lower()


def test_latency_is_rounded_to_three_decimals() -> None:
    report = run_probe(clock=StepClock(step=0.0001234))

    for _, result in report.capabilities:
        assert result.latency_ms == round(result.latency_ms, 3)


def test_overall_deadline_marks_remaining_capabilities_controlled_unavailable() -> None:
    clock = MutableClock()
    normal = FakeNormalProbeClient(catalog_hook=lambda: setattr(clock, "value", 2.0))

    report = run_probe(
        normal=normal,
        clock=clock,
        overall_hard_deadline_seconds=1.0,
        capability_hard_deadline_seconds=1.0,
    )

    assert report.capabilities.security_catalog.available is True
    for capability in CAPABILITY_NAMES[1:]:
        result = getattr(report.capabilities, capability)
        outcomes = getattr(report.manifest.source_outcomes, capability)
        assert result.available is False
        assert result.source == "probe.deadline"
        assert result.error is not None
        assert "ProbeDeadlineExceeded" in result.error
        assert len(outcomes) == 1
        assert outcomes[0].source == "probe.deadline"
        assert outcomes[0].attempted is False
        assert outcomes[0].status == "skipped"


def test_per_capability_deadline_stops_later_fallback_source_attempt() -> None:
    clock = MutableClock()

    class SlowNormalQuote(FakeNormalProbeClient):
        def get_security_quotes(
            self, stocks: list[tuple[Market, str]]
        ) -> pd.DataFrame:
            response = super().get_security_quotes(stocks)
            if clock.value == 0.0:
                clock.value = 2.0
            return response

    report = run_probe(
        normal=SlowNormalQuote(),
        clock=clock,
        overall_hard_deadline_seconds=100.0,
        capability_hard_deadline_seconds=1.0,
    )

    assert report.capabilities.quotes.available is True
    outcomes = report.manifest.source_outcomes.quotes
    assert [outcome.status for outcome in outcomes] == ["succeeded", "skipped"]
    assert outcomes[1].attempted is False
    assert "ProbeDeadlineExceeded" in (outcomes[1].error or "")


def test_board_dependency_skip_is_not_an_attempted_failure() -> None:
    report = run_probe(
        enhanced=FakeEnhancedProbeClient({"get_board_list"}),
    )

    outcome = report.manifest.source_outcomes.board_members[0]
    assert outcome.source == "tdx.enhanced.board-members"
    assert outcome.attempted is False
    assert outcome.status == "skipped"
    assert "discovery" in (outcome.error or "")


def test_board_model_failure_is_isolated_and_later_capabilities_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_board(**_kwargs: object) -> object:
        raise ValueError("unexpected board model failure at 192.0.2.1")

    monkeypatch.setattr(tdx_probe, "DiscoveredBoard", invalid_board)

    report = run_probe()

    outcomes = report.manifest.source_outcomes.board_list
    assert outcomes[0].source == "tdx.enhanced.board-list"
    assert outcomes[0].status == "succeeded"
    assert outcomes[-1].source == "probe.capability-isolation"
    assert outcomes[-1].status == "failed"
    assert "<host redacted>" in (outcomes[-1].error or "")
    assert report.capabilities.board_list.available is False
    assert report.manifest.source_outcomes.board_members[0].status == "skipped"
    assert report.capabilities.quotes.available is True


def test_enhanced_handicap_plan_failure_preserves_normal_order_book_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_plan() -> object:
        raise OverflowError("installed bitmap command construction failed")

    monkeypatch.setattr(tdx_probe, "enhanced_handicap_plan", fail_plan)

    report = run_probe()

    outcomes = report.manifest.source_outcomes.order_book
    assert [outcome.source for outcome in outcomes] == [
        "tdx.normal.order-book",
        "tdx.enhanced.order-book",
    ]
    assert [outcome.status for outcome in outcomes] == ["succeeded", "failed"]
    assert "OverflowError" in (outcomes[1].error or "")
    assert report.capabilities.order_book.available is True
