from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess

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
from workbench.providers.tdx.probe_validation import (
    MAX_SAMPLE_FIELDS,
    sanitized_error,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tdx"
FIXTURE_PATH = FIXTURE_DIR / "capability_probe.json"


def controlled_report() -> TdxCapabilityReport:
    error = "ProbeDeadlineExceeded: controlled test result"
    result = CapabilityResult(
        available=False,
        source="probe.deadline",
        latency_ms=0.0,
        sample_fields=[],
        error=error,
    )
    outcome = SourceOutcome(
        source="probe.deadline",
        attempted=True,
        status="failed",
        evidence=[],
        error=error,
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
            easy_tdx_version=version("easy-tdx"),
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


def create_tdx_home(tmp_path: Path, *, t0002: bool = False) -> Path:
    home = tmp_path / "tdx-home"
    cache = home / "T0002" / "hq_cache" if t0002 else home / "hq_cache"
    cache.mkdir(parents=True)
    (home / "vipdoc").mkdir()
    return home


@pytest.mark.parametrize(
    ("message", "forbidden"),
    [
        (
            "password=hunter2 username=alice host=10.20.30.40 "
            "C:\\Users\\alice\\private.txt\nTraceback: private frame",
            ("hunter2", "alice", "10.20.30.40", "C:\\Users", "Traceback"),
        ),
        ("decoder read /srv/tdx/private.bin", ("/srv/tdx",)),
        ("connection refused by [2001:db8::1]:7709", ("2001:db8::1",)),
        ("connection refused by private-node:7709", ("private-node:7709",)),
    ],
)
def test_sanitized_errors_remove_credentials_hosts_paths_and_stacks(
    message: str,
    forbidden: tuple[str, ...],
) -> None:
    summary = sanitized_error(RuntimeError(message))

    assert len(summary) <= 200
    assert "RuntimeError:" in summary
    for unsafe in forbidden:
        assert unsafe.lower() not in summary.lower()


def test_cli_atomically_writes_strict_report_without_modifying_tdx_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        real_replace(source, destination)

    monkeypatch.setattr("tools.probe_tdx_capabilities.os.replace", replace)

    exit_code = probe_cli.run(
        ["--tdx-home", str(home), "--output", str(output)],
        probe_runner=lambda _home, **_kwargs: controlled_report(),
    )

    assert exit_code == 0
    assert replace_calls and replace_calls[-1][1] == output
    assert TdxCapabilityReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert sorted(path.relative_to(home) for path in home.rglob("*")) == before_home
    assert not list(output.parent.glob("*.tmp"))


def test_cli_reports_invalid_tdx_home_without_leaking_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_home = tmp_path / "Users" / "private-user" / "missing-tdx"
    output = tmp_path / "must-not-exist.json"

    exit_code = probe_cli.run(
        ["--tdx-home", str(missing_home), "--output", str(output)],
        probe_runner=lambda _home, **_kwargs: pytest.fail("probe must not run"),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "TDX probe setup failed:" in captured.err
    assert str(missing_home) not in captured.err
    assert "Traceback" not in captured.err
    assert not output.exists()


def test_cli_accepts_standard_t0002_hq_cache_layout(tmp_path: Path) -> None:
    home = create_tdx_home(tmp_path, t0002=True)
    output = tmp_path / "capabilities.json"

    exit_code = probe_cli.run(
        ["--tdx-home", str(home), "--output", str(output)],
        probe_runner=lambda _home, **_kwargs: controlled_report(),
    )

    assert exit_code == 0
    assert TdxCapabilityReport.model_validate_json(output.read_text(encoding="utf-8"))


def test_atomic_replace_failure_preserves_old_output_and_sanitizes_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = create_tdx_home(tmp_path)
    output = tmp_path / "capabilities.json"
    output.write_text("old report", encoding="utf-8")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError(
            f"denied {output} password=hunter2 host=10.20.30.40\nTraceback: secret"
        )

    monkeypatch.setattr("tools.probe_tdx_capabilities.os.replace", fail_replace)

    exit_code = probe_cli.run(
        ["--tdx-home", str(home), "--output", str(output)],
        probe_runner=lambda _home, **_kwargs: controlled_report(),
    )

    captured = capsys.readouterr()
    assert exit_code == 3
    assert output.read_text(encoding="utf-8") == "old report"
    assert "TDX probe output failed:" in captured.err
    for forbidden in (str(output), "hunter2", "10.20.30.40", "Traceback"):
        assert forbidden not in captured.err
    assert not list(tmp_path.glob("*.tmp"))


def test_committed_real_fixture_matches_strict_generated_schema_and_privacy_audit() -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    fixture = TdxCapabilityReport.model_validate_json(raw)

    assert fixture.manifest.schema_version == PROBE_SCHEMA_VERSION
    assert fixture.manifest.probe_version == PROBE_VERSION
    assert fixture.manifest.captured_at.tzinfo is not None
    assert fixture.manifest.captured_at.utcoffset() is not None
    assert fixture.manifest.easy_tdx_version == version("easy-tdx")
    assert fixture.manifest.sample_symbol == "SH600000"
    assert fixture.manifest.discovered_board is not None
    assert set(fixture.manifest.source_outcomes.model_dump()) == set(CAPABILITY_NAMES)
    assert set(fixture.capabilities.model_dump()) == set(CAPABILITY_NAMES)
    for capability in CAPABILITY_NAMES:
        outcomes = getattr(fixture.manifest.source_outcomes, capability)
        assert outcomes
        assert len({outcome.source for outcome in outcomes}) == len(outcomes)
        for outcome in outcomes:
            assert len(outcome.evidence) <= MAX_SAMPLE_FIELDS
    for _, result in fixture.capabilities:
        assert result.latency_ms == round(result.latency_ms, 3)
        assert len(result.sample_fields) <= MAX_SAMPLE_FIELDS
    catalog_outcome = fixture.manifest.source_outcomes.security_catalog[0]
    assert catalog_outcome.attempted is True
    assert catalog_outcome.status == "failed"
    assert "SourceHardDeadlineExceeded" in (catalog_outcome.error or "")
    assert fixture.capabilities.security_catalog.latency_ms <= 20_100.0

    payload = json.loads(raw)
    assert set(payload) == {"manifest", "capabilities"}
    assert not re.search(
        r"(?i)(password|passwd|token|secret|api[-_]?key|username|hostname)",
        raw,
    )
    assert not re.search(
        r"(?i)([a-z]:[\\/]|\\\\[^\\]|/(?:home|users|var|tmp|srv)/)",
        raw,
    )
    assert not re.search(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", raw)
    assert "Traceback" not in raw

    readme = (FIXTURE_DIR / "README.md").read_text(encoding="utf-8")
    assert "manifest is the source of truth" in readme.lower()
    assert "capital-flow" in readme.lower()
    assert "date" in readme.lower()
    assert "upper bound" in readme.lower()
    assert "--max-node-attempts" in readme
    assert "--overall-hard-deadline-seconds" in readme
    assert "--worker-termination-grace-seconds" in readme
    assert "2026-08-20" not in readme
    assert "881234" not in readme


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
