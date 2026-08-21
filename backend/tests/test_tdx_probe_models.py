from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from workbench.domain import CapabilityResult, ProviderCapabilities
from workbench.providers.tdx.probe_models import (
    CAPABILITY_NAMES,
    PROBE_SCHEMA_VERSION,
    PROBE_VERSION,
    CapabilitySourceOutcomes,
    DiscoveredBoard,
    ProbeManifest,
    SourceOutcome,
    TdxCapabilityReport,
)


def capabilities() -> ProviderCapabilities:
    result = CapabilityResult(
        available=False,
        source="probe.deadline",
        latency_ms=0.0,
        sample_fields=[],
        error="ProbeDeadlineExceeded: deadline exhausted",
    )
    return ProviderCapabilities(
        **{name: result.model_copy() for name in ProviderCapabilities.model_fields}
    )


def source_outcomes() -> CapabilitySourceOutcomes:
    outcome = SourceOutcome(
        source="probe.deadline",
        attempted=True,
        status="failed",
        evidence=[],
        error="ProbeDeadlineExceeded: deadline exhausted",
    )
    return CapabilitySourceOutcomes(
        **{name: [outcome.model_copy()] for name in CAPABILITY_NAMES}
    )


def test_strict_report_round_trips_complete_generated_manifest() -> None:
    captured_at = datetime(
        2026,
        8,
        21,
        10,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )
    report = TdxCapabilityReport(
        manifest=ProbeManifest(
            schema_version=PROBE_SCHEMA_VERSION,
            probe_version=PROBE_VERSION,
            captured_at=captured_at,
            easy_tdx_version="1.20.7",
            sample_symbol="SH600000",
            discovered_board=DiscoveredBoard(id="881777", name="探针行业"),
            source_outcomes=source_outcomes(),
        ),
        capabilities=capabilities(),
    )

    restored = TdxCapabilityReport.model_validate_json(report.model_dump_json())

    assert restored == report
    assert restored.manifest.captured_at.utcoffset() == timedelta(hours=8)
    assert set(restored.manifest.source_outcomes.model_dump()) == set(CAPABILITY_NAMES)
    assert set(restored.capabilities.model_dump()) == set(CAPABILITY_NAMES)


def test_manifest_rejects_naive_capture_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ProbeManifest(
            schema_version=PROBE_SCHEMA_VERSION,
            probe_version=PROBE_VERSION,
            captured_at=datetime(2026, 8, 21, 10, 30),
            easy_tdx_version="1.20.7",
            sample_symbol="SH600000",
            discovered_board=None,
            source_outcomes=source_outcomes(),
        )


@pytest.mark.parametrize(
    ("status", "error"),
    [
        ("succeeded", "RuntimeError: contradictory"),
        ("failed", None),
    ],
)
def test_source_outcome_rejects_inconsistent_status_and_error(
    status: str,
    error: str | None,
) -> None:
    with pytest.raises(ValidationError):
        SourceOutcome.model_validate(
            {
                "source": "tdx.normal.quotes",
                "attempted": True,
                "status": status,
                "evidence": ["price"],
                "error": error,
            }
        )


def test_report_models_reject_extra_fields_and_missing_capability_outcomes() -> None:
    payload = source_outcomes().model_dump()
    payload.pop("order_book")

    with pytest.raises(ValidationError):
        CapabilitySourceOutcomes.model_validate(payload)

    with pytest.raises(ValidationError):
        DiscoveredBoard.model_validate(
            {"id": "881777", "name": "探针行业", "host": "not allowed"}
        )
