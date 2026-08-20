from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable

from easy_tdx import KlineCategory, Market
from easy_tdx.codec.bitmap import FieldBit, build_bitmap, normalize_fields
import pandas as pd
import pytest

from tools import probe_tdx_capabilities as probe_cli
from workbench.domain import CapabilityResult, ProviderCapabilities
from workbench.providers.tdx import probe as tdx_probe
from workbench.providers.tdx.probe import MAX_SAMPLE_FIELDS, probe_tdx_capabilities


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tdx"
FIXTURE_PATH = FIXTURE_DIR / "capability_probe.json"


class StepClock:
    def __init__(self, step: float = 0.01) -> None:
        self.value = -step
        self.step = step
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        self.value += self.step
        return self.value


class FakePool:
    def __init__(self, client: object) -> None:
        self.client = client

    def execute(self, operation: Callable[[Any], Any]) -> Any:
        return operation(self.client)


class FakeNormalClient:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.stock_requests: list[tuple[str, Market, str]] = []

    def _fail_if_requested(self, method: str) -> None:
        if method in self.failures:
            raise RuntimeError(
                "password=hunter2 username=alice host=10.20.30.40 "
                "C:\\Users\\alice\\tdx\\secret.txt\n"
                "Traceback (most recent call last):\n  File '/home/alice/probe.py'"
            )

    def get_security_count(self, market: Market) -> int:
        self._fail_if_requested("get_security_count")
        assert market is Market.SH
        return 2

    def get_security_list(self, market: Market, start: int) -> pd.DataFrame:
        self._fail_if_requested("get_security_list")
        assert market is Market.SH
        assert start == 0
        return pd.DataFrame(
            [
                {
                    "code": "600000",
                    "name": "浦发银行",
                    "volunit": 100,
                    "decimal_point": 2,
                },
                {
                    "code": "600001",
                    "name": "示例证券",
                    "volunit": 100,
                    "decimal_point": 2,
                },
            ]
        )

    def get_security_quotes(
        self, stocks: list[tuple[Market, str]]
    ) -> pd.DataFrame:
        self._fail_if_requested("get_security_quotes")
        self.stock_requests.append(("quotes", stocks[0][0], stocks[0][1]))
        return pd.DataFrame(
            [{"market": 1, "code": "600000", "price": 12.34, "last_close": 12.20}]
        )

    def get_transaction_data(
        self, market: Market, code: str, start: int, count: int = 800
    ) -> pd.DataFrame:
        self._fail_if_requested("get_transaction_data")
        self.stock_requests.append(("transactions", market, code))
        assert start == 0
        assert count <= 3
        return pd.DataFrame([{"time": "14:59", "price": 12.34, "vol": 2, "num": 1}])

    def get_minute_time_data(self, market: Market, code: str) -> pd.DataFrame:
        self._fail_if_requested("get_minute_time_data")
        self.stock_requests.append(("minute_data", market, code))
        return pd.DataFrame([{"price": 12.34, "vol": 100, "datetime": "2026-08-20T14:59"}])

    def get_security_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
    ) -> pd.DataFrame:
        self._fail_if_requested("get_security_bars")
        self.stock_requests.append(("bars", market, code))
        assert category is KlineCategory.DAY
        assert start == 0
        assert count <= 3
        return pd.DataFrame(
            [{"open": 12.0, "high": 12.5, "low": 11.9, "close": 12.34, "vol": 10}]
        )


class FakeMacClient:
    def __init__(
        self,
        failures: set[str] | None = None,
        *,
        capital_fields_verified: bool = True,
    ) -> None:
        self.failures = failures or set()
        self.capital_fields_verified = capital_fields_verified
        self.board_member_requests: list[str] = []
        self.stock_requests: list[tuple[str, int, str]] = []
        self.quote_fields: list[object] = []

    def _fail_if_requested(self, method: str) -> None:
        if method in self.failures:
            raise RuntimeError(f"{method} unavailable")

    def get_board_list(self, *, board_type: object, count: int) -> pd.DataFrame:
        self._fail_if_requested("get_board_list")
        assert getattr(board_type, "name", None) == "HY"
        assert count <= 8
        return pd.DataFrame(
            [
                {"market": 1, "code": "881777", "name": "探针行业一"},
                {"market": 1, "code": "881778", "name": "探针行业二"},
            ]
        )

    def get_board_members(self, board_symbol: str, *, count: int) -> pd.DataFrame:
        self._fail_if_requested("get_board_members")
        self.board_member_requests.append(board_symbol)
        assert count <= 3
        return pd.DataFrame(
            [{"market": 1, "code": "600000", "name": "浦发银行", "close": 12.34}]
        )

    def get_capital_flow(self, market: int, code: str) -> pd.DataFrame:
        self._fail_if_requested("get_capital_flow")
        self.stock_requests.append(("official_funds", market, code))
        if not self.capital_fields_verified:
            return pd.DataFrame([{"date": "20260820", "mystery_amount": 1.0}])
        return pd.DataFrame(
            [
                {
                    "date": "20260820",
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
        self, stocks: list[tuple[int, str]], fields: object = None
    ) -> pd.DataFrame:
        self._fail_if_requested("get_stock_quotes")
        self.stock_requests.append(("stock_quotes", stocks[0][0], stocks[0][1]))
        self.quote_fields.append(fields)
        selected = list(normalize_fields(fields))
        values = {
            bit.field_name: 1 if bit.fmt in {"<I", "<i"} else 12.34
            for bit in selected
        }
        return pd.DataFrame(
            [
                {
                    "market": stocks[0][0],
                    "code": "600000",
                    "name": "浦发银行",
                    **values,
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
        self._fail_if_requested("get_stock_kline")
        self.stock_requests.append(("stock_kline", market, code))
        assert getattr(period, "name", None) == "DAILY"
        assert start == 0
        assert count <= 3
        return pd.DataFrame(
            [{"datetime": "2026-08-20", "open": 12.0, "high": 12.5, "low": 11.9, "close": 12.34}]
        )


def run_probe(
    *,
    normal: FakeNormalClient | None = None,
    enhanced: FakeMacClient | None = None,
    clock: Callable[[], float] | None = None,
) -> ProviderCapabilities:
    return probe_tdx_capabilities(
        FakePool(normal or FakeNormalClient()),
        FakePool(enhanced or FakeMacClient()),
        clock=clock or StepClock(),
    )


def unavailable_report() -> ProviderCapabilities:
    result = CapabilityResult(
        available=False,
        source="tdx.controlled-unavailable",
        latency_ms=0.0,
        sample_fields=[],
        error="ControlledUnavailable: endpoint did not respond",
    )
    return ProviderCapabilities(
        **{name: result.model_copy() for name in ProviderCapabilities.model_fields}
    )


def create_tdx_home(tmp_path: Path) -> Path:
    home = tmp_path / "tdx-home"
    home.mkdir()
    (home / "hq_cache").mkdir()
    (home / "vipdoc").mkdir()
    return home


def test_probe_reports_exact_contract_and_uses_real_discovered_board() -> None:
    normal = FakeNormalClient()
    enhanced = FakeMacClient()

    report = run_probe(normal=normal, enhanced=enhanced)

    assert set(report.model_dump()) == set(ProviderCapabilities.model_fields) == {
        "security_catalog",
        "board_list",
        "board_members",
        "official_funds",
        "quotes",
        "transactions",
        "minute_data",
        "bars",
        "order_book",
    }
    assert enhanced.board_member_requests == ["881777"]
    assert all(market is Market.SH and code == "600000" for _, market, code in normal.stock_requests)
    assert all(
        market == int(Market.SH) and code == "600000"
        for _, market, code in enhanced.stock_requests
    )
    assert enhanced.quote_fields and all(fields is not None for fields in enhanced.quote_fields)


def test_every_real_enhanced_field_selection_fits_installed_bitmap() -> None:
    selections = {
        "quotes": tdx_probe.ENHANCED_QUOTE_FIELDS,
        "order_book": tdx_probe.ENHANCED_ORDER_BOOK_FIELDS,
    }

    for name, selection in selections.items():
        bitmap = build_bitmap(selection)
        selected_bits = list(normalize_fields(selection))

        assert len(bitmap) == 20, name
        assert selected_bits, name
        assert max(bit.value for bit in selected_bits) < 128, name


def test_order_book_verifies_level_one_two_then_reports_local_five_level_limit() -> None:
    enhanced = FakeMacClient()

    report = run_probe(enhanced=enhanced)

    assert len(enhanced.quote_fields) == 2
    quote_fields, order_book_fields = enhanced.quote_fields
    quote_names = {bit.field_name for bit in normalize_fields(quote_fields)}
    order_book_names = {
        bit.field_name for bit in normalize_fields(order_book_fields)
    }
    assert "close" in quote_names
    assert {
        FieldBit.BID_PRICE.field_name,
        FieldBit.ASK_PRICE.field_name,
        FieldBit.BID_VOLUME.field_name,
        FieldBit.ASK_VOLUME.field_name,
        FieldBit.BID2_PRICE.field_name,
        FieldBit.ASK2_PRICE.field_name,
        FieldBit.BID2_VOLUME.field_name,
        FieldBit.ASK2_VOLUME.field_name,
    } <= order_book_names
    assert order_book_names.isdisjoint(
        {"bid3_price", "ask3_price", "bid5_volume", "ask5_volume"}
    )
    assert report.quotes.available is True
    assert report.order_book.available is False
    assert report.order_book.sample_fields == []
    assert report.order_book.error is not None
    assert report.order_book.error.startswith("LocalClientCapabilityLimitation:")
    assert "levels 3-5" in report.order_book.error
    assert "128-bit" in report.order_book.error


def test_one_capability_failure_does_not_hide_successful_capabilities() -> None:
    report = run_probe(normal=FakeNormalClient({"get_transaction_data"}))

    assert report.transactions.available is False
    assert report.transactions.sample_fields == []
    assert report.transactions.error is not None
    assert all(
        getattr(report, name).available
        for name in ProviderCapabilities.model_fields
        if name not in {"transactions", "order_book"}
    )


def test_each_result_has_valid_semantics_and_per_capability_monotonic_latency() -> None:
    clock = StepClock(step=0.025)

    report = run_probe(clock=clock)

    assert clock.calls == len(ProviderCapabilities.model_fields) * 2
    for name, capability in report:
        assert isinstance(capability, CapabilityResult)
        assert capability.source
        assert capability.latency_ms == pytest.approx(25.0)
        assert capability.latency_ms >= 0
        if name == "order_book":
            assert capability.available is False
            assert capability.error is not None
            assert capability.sample_fields == []
        else:
            assert capability.available is True
            assert capability.error is None
            assert capability.sample_fields


def test_samples_are_bounded_serializable_and_recursively_remove_secrets() -> None:
    class UnsafeCatalogClient(FakeNormalClient):
        def get_security_list(self, market: Market, start: int) -> list[dict[str, object]]:
            assert market is Market.SH
            assert start == 0
            return [
                {
                    "code": "600000",
                    "name": "浦发银行",
                    "nested": {
                        "safe_field": 1,
                        "password": "hunter2",
                        "host": "secret.internal",
                        "C:\\Users\\alice\\private.txt": "never record this",
                    },
                    **{f"field_{index}": index for index in range(30)},
                }
            ]

    report = run_probe(normal=UnsafeCatalogClient({"get_transaction_data"}))
    payload = report.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False)

    assert all(
        len(result.sample_fields) <= MAX_SAMPLE_FIELDS
        for _, result in report
    )
    assert json.loads(encoded) == payload
    for forbidden in (
        "hunter2",
        "alice",
        "10.20.30.40",
        "secret.internal",
        "C:\\Users",
        "/home/",
        "Traceback",
        "password",
        "username",
    ):
        assert forbidden.lower() not in encoded.lower()


@pytest.mark.parametrize(
    ("message", "forbidden"),
    [
        ("decoder read /srv/tdx/private.bin", "/srv/tdx"),
        ("connection refused by [2001:db8::1]:7709", "2001:db8::1"),
        ("connection refused by private-node:7709", "private-node:7709"),
        ("decoder failed\nTraceback: private frame", "Traceback"),
    ],
)
def test_errors_redact_all_host_path_and_stack_styles(
    message: str, forbidden: str
) -> None:
    class UnsafeErrorClient(FakeNormalClient):
        def get_transaction_data(
            self, market: Market, code: str, start: int, count: int = 800
        ) -> pd.DataFrame:
            raise RuntimeError(message)

    report = run_probe(normal=UnsafeErrorClient())
    encoded = report.model_dump_json()

    assert report.transactions.available is False
    assert forbidden.lower() not in encoded.lower()


def test_official_funds_is_unavailable_when_protocol_fields_are_unverified() -> None:
    report = run_probe(enhanced=FakeMacClient(capital_fields_verified=False))

    assert report.official_funds.available is False
    assert report.official_funds.sample_fields == []
    assert "required protocol fields" in (report.official_funds.error or "").lower()
    assert report.board_list.available is True
    assert report.quotes.available is True


def test_cli_atomically_writes_a_complete_unavailable_report_with_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = create_tdx_home(tmp_path)
    output = tmp_path / "capture" / "capabilities.json"
    output.parent.mkdir()
    output.write_text("old report", encoding="utf-8")
    before_home = sorted(path.relative_to(home) for path in home.rglob("*"))
    replace_calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        replace_calls.append((source_path, destination_path))
        assert source_path.parent == destination_path.parent == output.parent
        assert source_path != destination_path
        real_replace(source, destination)

    monkeypatch.setattr(probe_cli.os, "replace", replace)

    exit_code = probe_cli.run(
        ["--tdx-home", str(home), "--output", str(output)],
        probe_runner=lambda _home: unavailable_report(),
    )

    assert exit_code == 0
    assert replace_calls and replace_calls[-1][1] == output
    assert ProviderCapabilities.model_validate_json(output.read_text(encoding="utf-8"))
    assert sorted(path.relative_to(home) for path in home.rglob("*")) == before_home
    assert not list(output.parent.glob("*.tmp"))


def test_cli_reports_invalid_tdx_home_without_leaking_the_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_home = tmp_path / "Users" / "private-user" / "missing-tdx"
    output = tmp_path / "must-not-exist.json"

    exit_code = probe_cli.run(
        ["--tdx-home", str(missing_home), "--output", str(output)],
        probe_runner=lambda _home: pytest.fail("probe must not run after setup failure"),
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "TDX probe setup failed:" in captured.err
    assert str(missing_home) not in captured.err
    assert "Traceback" not in captured.err
    assert not output.exists()


def test_cli_accepts_standard_t0002_hq_cache_layout(tmp_path: Path) -> None:
    home = tmp_path / "tdx-home"
    (home / "T0002" / "hq_cache").mkdir(parents=True)
    (home / "vipdoc").mkdir()
    output = tmp_path / "capabilities.json"

    exit_code = probe_cli.run(
        ["--tdx-home", str(home), "--output", str(output)],
        probe_runner=lambda _home: unavailable_report(),
    )

    assert exit_code == 0
    assert ProviderCapabilities.model_validate_json(output.read_text(encoding="utf-8"))


def test_cli_returns_nonzero_and_preserves_old_output_on_atomic_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = create_tdx_home(tmp_path)
    output = tmp_path / "capabilities.json"
    output.write_text("old report", encoding="utf-8")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError(
            f"denied {output} password=hunter2 host=10.20.30.40\nTraceback: secret"
        )

    monkeypatch.setattr(probe_cli.os, "replace", fail_replace)

    exit_code = probe_cli.run(
        ["--tdx-home", str(home), "--output", str(output)],
        probe_runner=lambda _home: unavailable_report(),
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert output.read_text(encoding="utf-8") == "old report"
    assert "TDX probe output failed:" in captured.err
    for forbidden in (str(output), "hunter2", "10.20.30.40", "Traceback"):
        assert forbidden not in captured.err
    assert not list(tmp_path.glob("*.tmp"))


def test_committed_real_fixture_matches_strict_model_and_has_no_secrets() -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")

    fixture = ProviderCapabilities.model_validate_json(raw)

    assert set(fixture.model_dump()) == set(ProviderCapabilities.model_fields)
    assert all(len(result.sample_fields) <= MAX_SAMPLE_FIELDS for _, result in fixture)
    assert not re.search(r"(?i)(password|passwd|token|secret|api[-_]?key|username)", raw)
    assert not re.search(r"(?i)([a-z]:[\\/]|\\\\[^\\]|/(?:home|users|var|tmp)/)", raw)
    assert not re.search(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", raw)
    assert "Traceback" not in raw
    assert fixture.order_book.available is False
    assert fixture.order_book.error is not None
    assert fixture.order_book.error.startswith("LocalClientCapabilityLimitation:")
    assert "OverflowError" not in fixture.order_book.error
    readme = (FIXTURE_DIR / "README.md").read_text(encoding="utf-8")
    for expected in ("2026-08-20", "SH600000", "board", "live", "available=false", "refresh"):
        assert expected.lower() in readme.lower()
    assert "local installed-client limitation" in readme.lower()
    assert "all nine entries are live endpoint evidence" not in readme.lower()


def test_raw_probe_outputs_are_ignored_but_sanitized_fixture_is_not() -> None:
    raw_paths = (
        "data/run/tdx-capability-probe.raw.json",
        "backend/data/run/.tdx-capability-probe.json.tmp",
    )
    for raw_path in raw_paths:
        ignored = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", raw_path],
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        assert ignored.returncode == 0, raw_path

    fixture_path = FIXTURE_PATH.relative_to(REPOSITORY_ROOT)
    sanitized = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", str(fixture_path)],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    assert sanitized.returncode == 1
