from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_collector(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "workbench.collector.main", *arguments],
        cwd=BACKEND_DIR,
        text=True,
        capture_output=True,
        check=False,
    )


def collector_arguments(data_dir: Path) -> list[str]:
    return [
        "--fake",
        "--once",
        "--date",
        "2026-08-20",
        "--minute",
        "09:31",
        "--data-dir",
        str(data_dir),
        "--stocks",
        "100",
        "--sectors",
        "4",
    ]


def test_fake_once_collects_one_complete_minute(tmp_path: Path) -> None:
    completed = run_collector(*collector_arguments(tmp_path / "data"))

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["collected_stocks"] == 100
    assert payload["collected_sectors"] == 4
    assert payload["coverage_pct"] == 100.0
    assert payload["status"] == "complete"


def test_fake_once_is_idempotent_for_the_same_minute(tmp_path: Path) -> None:
    arguments = collector_arguments(tmp_path / "data")

    first = run_collector(*arguments)
    second = run_collector(*arguments)

    assert first.returncode == second.returncode == 0
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    first_payload.pop("duration_ms")
    second_payload.pop("duration_ms")
    assert first_payload == second_payload


def test_capacity_probe_emits_a_successful_json_report() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/benchmark_minute_batch.py"],
        cwd=BACKEND_DIR,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["budget_seconds"] == 45.0
    assert payload["wall_seconds"] <= payload["budget_seconds"]
    assert payload["status"]["coverage_pct"] == 100.0
    assert payload["status"]["collected_stocks"] == 5_500
    assert payload["status"]["collected_sectors"] == 400


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--once"], "--fake is required"),
        (["--fake"], "--once is required"),
        (["--fake", "--once", "--date", "2026-08-99"], "invalid ISO date"),
        (["--fake", "--once", "--minute", "9:31"], "invalid HH:MM minute"),
        (["--fake", "--once", "--stocks", "1.5"], "stocks must be an integer"),
        (["--fake", "--once", "--sectors", "-1"], "sectors must be nonnegative"),
        (["--fake", "--once", "--stocks", "2", "--sectors", "1", "--members-per-sector", "3"], "cannot exceed stocks"),
    ],
)
def test_cli_rejects_invalid_phase_or_inputs_without_traceback(
    tmp_path: Path, arguments: list[str], message: str
) -> None:
    completed = run_collector(
        "--date",
        "2026-08-20",
        "--minute",
        "09:31",
        "--data-dir",
        str(tmp_path / "data"),
        *arguments,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert message in completed.stderr
    assert "Traceback" not in completed.stderr
