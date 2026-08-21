from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
from typing import Any, cast

from collections.abc import Iterable

import pytest

from tools import probe_tdx_capabilities as probe_cli
from workbench.domain import CapabilityResult, ProviderCapabilities
from workbench.providers.tdx.probe_models import (
    CAPABILITY_NAMES,
    PROBE_SCHEMA_VERSION,
    PROBE_VERSION,
    CapabilitySourceOutcomes,
    ProbeManifest,
    SourceOutcome,
    TdxCapabilityReport,
)


def strict_report() -> TdxCapabilityReport:
    result = CapabilityResult(
        available=False,
        source="probe.deadline",
        latency_ms=0.0,
        sample_fields=[],
        error="ProbeDeadlineExceeded: controlled test result",
    )
    outcome = SourceOutcome(
        source="probe.deadline",
        attempted=True,
        status="failed",
        evidence=[],
        error="ProbeDeadlineExceeded: controlled test result",
    )
    return TdxCapabilityReport(
        manifest=ProbeManifest(
            schema_version=PROBE_SCHEMA_VERSION,
            probe_version=PROBE_VERSION,
            captured_at=datetime(
                2026,
                8,
                21,
                12,
                0,
                tzinfo=timezone(timedelta(hours=8)),
            ),
            easy_tdx_version="1.20.7",
            sample_symbol="SH600000",
            discovered_board=None,
            source_outcomes=CapabilitySourceOutcomes(
                **{name: [outcome.model_copy()] for name in CAPABILITY_NAMES}
            ),
        ),
        capabilities=ProviderCapabilities(
            **{name: result.model_copy() for name in CAPABILITY_NAMES}
        ),
    )


def create_tdx_home(tmp_path: Path) -> Path:
    home = tmp_path / "tdx-home"
    (home / "hq_cache").mkdir(parents=True)
    (home / "vipdoc").mkdir()
    return home


def test_cli_exposes_explicit_bounded_probe_defaults() -> None:
    options = probe_cli.build_parser().parse_args(
        ["--tdx-home", "C:/tdx", "--output", "capture.json"]
    )

    assert options.max_node_attempts == 2
    assert options.socket_timeout_seconds == 3.0
    assert options.overall_deadline_seconds == 120.0
    assert options.capability_deadline_seconds == 20.0

    for flag, value in (
        ("--max-node-attempts", "0"),
        ("--socket-timeout-seconds", "nan"),
        ("--overall-deadline-seconds", "-1"),
        ("--capability-deadline-seconds", "0"),
    ):
        with pytest.raises(SystemExit):
            probe_cli.build_parser().parse_args(
                [
                    "--tdx-home",
                    "C:/tdx",
                    "--output",
                    "capture.json",
                    flag,
                    value,
                ]
            )


def test_live_probe_limits_targets_and_forwards_socket_and_deadline_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = create_tdx_home(tmp_path)
    created: dict[str, FakePool] = {}

    class FakePool:
        def __init__(self, targets: object, **kwargs: object) -> None:
            self.targets = list(cast(Iterable[object], targets))
            self.kwargs = kwargs
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    def normal_pool(targets: object, **kwargs: object) -> FakePool:
        created["normal"] = FakePool(targets, **kwargs)
        return created["normal"]

    def enhanced_pool(targets: object, **kwargs: object) -> FakePool:
        created["enhanced"] = FakePool(targets, **kwargs)
        return created["enhanced"]

    forwarded: dict[str, object] = {}

    def probe(_normal: object, _enhanced: object, **kwargs: object) -> TdxCapabilityReport:
        forwarded.update(kwargs)
        return strict_report()

    monkeypatch.setattr(probe_cli, "TdxNodePool", normal_pool)
    monkeypatch.setattr(probe_cli, "MacNodePool", enhanced_pool)
    monkeypatch.setattr(probe_cli, "probe_tdx_capabilities", probe)
    monkeypatch.setattr(probe_cli, "KNOWN_HOSTS", tuple(f"normal-{i}" for i in range(8)))
    monkeypatch.setattr(probe_cli, "MAC_HOSTS", tuple(f"enhanced-{i}" for i in range(8)))

    report = probe_cli.run_live_probe(
        home,
        max_node_attempts=2,
        socket_timeout_seconds=1.25,
        overall_deadline_seconds=7.0,
        capability_deadline_seconds=2.0,
    )

    assert report == strict_report()
    assert len(created["normal"].targets) == 2
    assert len(created["enhanced"].targets) == 2
    assert created["normal"].kwargs["timeout_seconds"] == 1.25
    assert created["enhanced"].kwargs["timeout_seconds"] == 1.25
    assert forwarded == {
        "overall_deadline_seconds": 7.0,
        "capability_deadline_seconds": 2.0,
    }
    assert created["normal"].close_calls == 1
    assert created["enhanced"].close_calls == 1


class ClosingPool:
    def __init__(self, label: str, events: list[str], *, fail: bool = False) -> None:
        self.label = label
        self.events = events
        self.fail = fail

    def close(self) -> None:
        self.events.append(self.label)
        if self.fail:
            raise RuntimeError(f"{self.label} close failed")


def test_normal_close_failure_still_closes_enhanced() -> None:
    events: list[str] = []

    with pytest.raises(probe_cli.ProbeCleanupError) as captured:
        probe_cli._close_probe_pools(
            ClosingPool("normal", events, fail=True),
            ClosingPool("enhanced", events),
        )

    assert events == ["normal", "enhanced"]
    assert len(captured.value.errors) == 1


def test_both_close_failures_are_reported_together() -> None:
    events: list[str] = []

    with pytest.raises(probe_cli.ProbeCleanupError) as captured:
        probe_cli._close_probe_pools(
            ClosingPool("normal", events, fail=True),
            ClosingPool("enhanced", events, fail=True),
        )

    assert events == ["normal", "enhanced"]
    assert len(captured.value.errors) == 2


def test_primary_probe_exception_is_preserved_and_cleanup_failures_are_chained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = create_tdx_home(tmp_path)
    events: list[str] = []
    pools = iter(
        [
            ClosingPool("normal", events, fail=True),
            ClosingPool("enhanced", events, fail=True),
        ]
    )
    monkeypatch.setattr(probe_cli, "TdxNodePool", lambda *_args, **_kwargs: next(pools))
    monkeypatch.setattr(probe_cli, "MacNodePool", lambda *_args, **_kwargs: next(pools))

    primary = RuntimeError("primary probe failure")

    def fail_probe(*_args: object, **_kwargs: object) -> TdxCapabilityReport:
        raise primary

    monkeypatch.setattr(probe_cli, "probe_tdx_capabilities", fail_probe)

    with pytest.raises(RuntimeError, match="primary probe failure") as captured:
        probe_cli.run_live_probe(
            home,
            max_node_attempts=1,
            socket_timeout_seconds=0.1,
            overall_deadline_seconds=1.0,
            capability_deadline_seconds=0.5,
        )

    assert captured.value is primary
    assert events == ["normal", "enhanced"]
    assert isinstance(captured.value.__cause__, probe_cli.ProbeCleanupError)
    assert len(captured.value.__cause__.errors) == 2


def test_cli_writes_and_revalidates_strict_report_wrapper(tmp_path: Path) -> None:
    home = create_tdx_home(tmp_path)
    output = tmp_path / "capture" / "capability_probe.json"

    exit_code = probe_cli.run(
        ["--tdx-home", str(home), "--output", str(output)],
        probe_runner=lambda _home, **_kwargs: strict_report(),
    )

    assert exit_code == 0
    restored = TdxCapabilityReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert restored == strict_report()


def test_atomic_writer_closes_raw_descriptor_when_fdopen_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "capability_probe.json"
    descriptor, temporary_name = tempfile.mkstemp(dir=tmp_path)
    closed: list[int] = []
    real_close = os.close

    monkeypatch.setattr(
        "tools.probe_tdx_capabilities.tempfile.mkstemp",
        lambda **_kwargs: (descriptor, temporary_name),
    )

    def fail_fdopen(*_args: object, **_kwargs: object) -> Any:
        raise OSError("fdopen failed")

    def close(raw_descriptor: int) -> None:
        closed.append(raw_descriptor)
        real_close(raw_descriptor)

    monkeypatch.setattr("tools.probe_tdx_capabilities.os.fdopen", fail_fdopen)
    monkeypatch.setattr("tools.probe_tdx_capabilities.os.close", close)

    with pytest.raises(OSError, match="fdopen failed"):
        probe_cli._atomic_write_report(output, strict_report())

    assert closed == [descriptor]
    assert not Path(temporary_name).exists()
    assert not output.exists()
