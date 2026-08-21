from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
import math
import os
from pathlib import Path
import sys
import tempfile


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from easy_tdx.config import get_port
from easy_tdx.transport.sync import KNOWN_HOSTS, MAC_HOSTS

from workbench.config import WorkbenchSettings
from workbench.providers.tdx.clients import EnhancedProbeClient, NormalProbeClient
from workbench.providers.tdx.node_pool import MacNodePool, NodeTarget, TdxNodePool
from workbench.providers.tdx.probe import probe_tdx_capabilities
from workbench.providers.tdx.probe_models import TdxCapabilityReport
from workbench.providers.tdx.probe_validation import sanitized_error


ProbeRunner = Callable[..., TdxCapabilityReport]

DEFAULT_MAX_NODE_ATTEMPTS = 2
DEFAULT_SOCKET_TIMEOUT_SECONDS = 3.0
DEFAULT_OVERALL_DEADLINE_SECONDS = 120.0
DEFAULT_CAPABILITY_DEADLINE_SECONDS = 20.0


class ProbeSetupError(RuntimeError):
    pass


class ProbeCleanupError(RuntimeError):
    def __init__(self, errors: Sequence[BaseException]) -> None:
        self.errors = tuple(errors)
        super().__init__(f"{len(self.errors)} TDX probe pool cleanup operation(s) failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe real TDX protocol capabilities and write a sanitized report."
    )
    parser.add_argument("--tdx-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--max-node-attempts",
        type=_positive_int,
        default=DEFAULT_MAX_NODE_ATTEMPTS,
        help="maximum target nodes each protocol source may try (default: 2)",
    )
    parser.add_argument(
        "--socket-timeout-seconds",
        type=_positive_float,
        default=DEFAULT_SOCKET_TIMEOUT_SECONDS,
        help="socket timeout for each target attempt (default: 3.0)",
    )
    parser.add_argument(
        "--overall-deadline-seconds",
        type=_positive_float,
        default=DEFAULT_OVERALL_DEADLINE_SECONDS,
        help="overall cooperative probe deadline (default: 120.0)",
    )
    parser.add_argument(
        "--capability-deadline-seconds",
        type=_positive_float,
        default=DEFAULT_CAPABILITY_DEADLINE_SECONDS,
        help="cooperative deadline per capability (default: 20.0)",
    )
    return parser


def run(
    arguments: Sequence[str] | None = None,
    *,
    probe_runner: ProbeRunner | None = None,
) -> int:
    options = build_parser().parse_args(arguments)
    try:
        _validate_tdx_home(options.tdx_home)
        report = (probe_runner or run_live_probe)(
            options.tdx_home,
            max_node_attempts=options.max_node_attempts,
            socket_timeout_seconds=options.socket_timeout_seconds,
            overall_deadline_seconds=options.overall_deadline_seconds,
            capability_deadline_seconds=options.capability_deadline_seconds,
        )
        report = TdxCapabilityReport.model_validate(report)
    except Exception as exc:
        print(f"TDX probe setup failed: {sanitized_error(exc)}", file=sys.stderr)
        return 2

    try:
        _atomic_write_report(options.output, report)
    except Exception as exc:
        print(f"TDX probe output failed: {sanitized_error(exc)}", file=sys.stderr)
        return 3
    return 0


def run_live_probe(
    tdx_home: Path,
    *,
    max_node_attempts: int = DEFAULT_MAX_NODE_ATTEMPTS,
    socket_timeout_seconds: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
    overall_deadline_seconds: float = DEFAULT_OVERALL_DEADLINE_SECONDS,
    capability_deadline_seconds: float = DEFAULT_CAPABILITY_DEADLINE_SECONDS,
) -> TdxCapabilityReport:
    _validate_positive_integer("max_node_attempts", max_node_attempts)
    _validate_positive_number("socket_timeout_seconds", socket_timeout_seconds)
    _validate_positive_number("overall_deadline_seconds", overall_deadline_seconds)
    _validate_positive_number(
        "capability_deadline_seconds", capability_deadline_seconds
    )
    settings = WorkbenchSettings(tdx_home=tdx_home)
    port = get_port()
    target_limit = min(max_node_attempts, settings.node_pool_size)
    normal_targets = [
        NodeTarget(address=address, port=port)
        for address in KNOWN_HOSTS[:target_limit]
    ]
    enhanced_targets = [
        NodeTarget(address=address, port=port)
        for address in MAC_HOSTS[:target_limit]
    ]
    normal_pool: TdxNodePool[NormalProbeClient] = TdxNodePool(
        normal_targets,
        timeout_seconds=socket_timeout_seconds,
        failure_threshold=max(settings.node_retry_count, 1),
    )
    enhanced_pool: MacNodePool[EnhancedProbeClient] = MacNodePool(
        enhanced_targets,
        timeout_seconds=socket_timeout_seconds,
        failure_threshold=max(settings.node_retry_count, 1),
    )
    try:
        report = probe_tdx_capabilities(
            normal_pool,
            enhanced_pool,
            overall_deadline_seconds=overall_deadline_seconds,
            capability_deadline_seconds=capability_deadline_seconds,
        )
    except BaseException as primary:
        try:
            _close_probe_pools(normal_pool, enhanced_pool)
        except ProbeCleanupError as cleanup:
            raise primary from cleanup
        raise
    _close_probe_pools(normal_pool, enhanced_pool)
    return report


def _close_probe_pools(normal_pool: object, enhanced_pool: object) -> None:
    errors: list[BaseException] = []
    for pool in (normal_pool, enhanced_pool):
        try:
            close = getattr(pool, "close")
            close()
        except BaseException as exc:
            errors.append(exc)
    if errors:
        raise ProbeCleanupError(errors)


def _validate_tdx_home(tdx_home: Path) -> None:
    try:
        if not tdx_home.is_dir():
            raise ProbeSetupError("local TDX home is unavailable")
        hq_cache_available = any(
            candidate.is_dir()
            for candidate in (tdx_home / "hq_cache", tdx_home / "T0002" / "hq_cache")
        )
        missing = []
        if not hq_cache_available:
            missing.append("hq_cache")
        if not (tdx_home / "vipdoc").is_dir():
            missing.append("vipdoc")
    except OSError as exc:
        raise ProbeSetupError("local TDX home could not be inspected") from exc
    if missing:
        raise ProbeSetupError(
            "local TDX home is missing required directories: " + ", ".join(missing)
        )


def _atomic_write_report(output: Path, report: TdxCapabilityReport) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    descriptor_open = True
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor_open = False
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output)
    except BaseException:
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be finite and positive") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be finite and positive")
    return parsed


def _validate_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_positive_number(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
