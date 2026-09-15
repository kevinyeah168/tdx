from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from workbench.collector.main import build_parser, parse_arguments


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


def test_cli_uses_the_documented_default_data_directory() -> None:
    arguments = parse_arguments(
        ["--fake", "--once", "--date", "2026-08-20", "--minute", "09:31"]
    )

    assert arguments.data_dir == Path("../data")
    assert arguments.stocks == 5_500
    assert arguments.sectors == 400
    assert arguments.members_per_sector == 80


def test_cli_help_documents_the_default_data_directory() -> None:
    assert "default: ../data" in build_parser().format_help()


def test_cli_controls_existing_file_data_directory_failure(tmp_path: Path) -> None:
    data_file = tmp_path / "not-a-directory"
    data_file.write_text("not a directory", encoding="utf-8")

    completed = run_collector(*collector_arguments(data_file))

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "collector setup failed:" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_fixture_real_provider_collects_one_minute(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "tdx"
    completed = run_collector(
        "--once",
        "--date",
        "2026-08-20",
        "--minute",
        "09:31",
        "--data-dir",
        str(tmp_path / "data"),
        "--fixture-dir",
        str(fixture_dir),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["collected_stocks"] == 3
    assert payload["collected_sectors"] == 2
    assert payload["status"] == "complete"


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
    assert payload["setup_seconds"] >= 0.0
    assert payload["wall_seconds"] <= payload["budget_seconds"]
    assert payload["coverage_pct"] == 100.0
    assert payload["collected_stocks"] == 5_500
    assert payload["collected_sectors"] == 400


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--date", "2026-08-20"], "--once, --serve, or --backfill-classic-indices is required"),
        ([], "--once, --serve, or --backfill-classic-indices is required"),
        (["--once", "--date", "2026-08-99", "--minute", "09:31"], "invalid ISO date"),
        (["--once", "--date", "2026-08-20", "--minute", "9:31"], "invalid HH:MM minute"),
        (["--fake", "--once", "--date", "2026-08-20", "--minute", "09:31", "--stocks", "1.5"], "stocks must be an integer"),
        (["--fake", "--once", "--date", "2026-08-20", "--minute", "09:31", "--sectors", "-1"], "sectors must be nonnegative"),
        (["--fake", "--once", "--date", "2026-08-20", "--minute", "09:31", "--stocks", "2", "--sectors", "1", "--members-per-sector", "3"], "cannot exceed stocks"),
    ],
)
def test_cli_rejects_invalid_phase_or_inputs_without_traceback(
    tmp_path: Path, arguments: list[str], message: str
) -> None:
    base_arguments = [
        "--date",
        "2026-08-20",
        "--minute",
        "09:31",
        "--data-dir",
        str(tmp_path / "data"),
    ]
    if message == "--once, --serve, or --backfill-classic-indices is required":
        base_arguments = ["--data-dir", str(tmp_path / "data")]
    completed = run_collector(*base_arguments, *arguments)

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert message in completed.stderr
    assert "Traceback" not in completed.stderr
