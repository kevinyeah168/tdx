from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
from typing import Any

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
    assert options.overall_hard_deadline_seconds == 120.0
    assert options.capability_hard_deadline_seconds == 20.0
    assert options.worker_termination_grace_seconds == 0.1

    for flag, value in (
        ("--max-node-attempts", "0"),
        ("--socket-timeout-seconds", "nan"),
        ("--overall-hard-deadline-seconds", "-1"),
        ("--capability-hard-deadline-seconds", "0"),
        ("--worker-termination-grace-seconds", "inf"),
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
    created: dict[str, object] = {}

    class FakeExecutor:
        def __init__(self, config: object, *, termination_grace_seconds: float) -> None:
            created["config"] = config
            created["termination_grace_seconds"] = termination_grace_seconds

    forwarded: dict[str, object] = {}

    def probe(**kwargs: object) -> TdxCapabilityReport:
        forwarded.update(kwargs)
        return strict_report()

    monkeypatch.setattr(probe_cli, "ProcessSourceExecutor", FakeExecutor)
    monkeypatch.setattr(probe_cli, "probe_tdx_capabilities", probe)
    monkeypatch.setattr(probe_cli, "KNOWN_HOSTS", tuple(f"normal-{i}" for i in range(8)))
    monkeypatch.setattr(probe_cli, "MAC_HOSTS", tuple(f"enhanced-{i}" for i in range(8)))

    report = probe_cli.run_live_probe(
        home,
        max_node_attempts=2,
        socket_timeout_seconds=1.25,
        overall_hard_deadline_seconds=7.0,
        capability_hard_deadline_seconds=2.0,
        worker_termination_grace_seconds=0.05,
    )

    assert report == strict_report()
    config = created["config"]
    assert len(config.normal_targets) == 2
    assert len(config.enhanced_targets) == 2
    assert config.socket_timeout_seconds == 1.25
    assert created["termination_grace_seconds"] == 0.05
    source_executor = forwarded.pop("source_executor")
    assert source_executor.__class__ is FakeExecutor
    assert forwarded == {
        "overall_hard_deadline_seconds": 7.0,
        "capability_hard_deadline_seconds": 2.0,
    }


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
