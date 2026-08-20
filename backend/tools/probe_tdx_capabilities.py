from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
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
from workbench.domain import ProviderCapabilities
from workbench.providers.tdx.node_pool import MacNodePool, NodeTarget, TdxNodePool
from workbench.providers.tdx.probe import probe_tdx_capabilities, sanitized_error


ProbeRunner = Callable[[Path], ProviderCapabilities]


class ProbeSetupError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe real TDX protocol capabilities and write a sanitized report."
    )
    parser.add_argument("--tdx-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def run(
    arguments: Sequence[str] | None = None,
    *,
    probe_runner: ProbeRunner | None = None,
) -> int:
    options = build_parser().parse_args(arguments)
    try:
        _validate_tdx_home(options.tdx_home)
        report = (probe_runner or run_live_probe)(options.tdx_home)
        report = ProviderCapabilities.model_validate(report)
    except Exception as exc:
        print(f"TDX probe setup failed: {sanitized_error(exc)}", file=sys.stderr)
        return 2

    try:
        _atomic_write_report(options.output, report)
    except Exception as exc:
        print(f"TDX probe output failed: {sanitized_error(exc)}", file=sys.stderr)
        return 3
    return 0


def run_live_probe(tdx_home: Path) -> ProviderCapabilities:
    settings = WorkbenchSettings(tdx_home=tdx_home)
    port = get_port()
    normal_targets = [
        NodeTarget(address=address, port=port)
        for address in KNOWN_HOSTS[: settings.node_pool_size]
    ]
    enhanced_targets = [
        NodeTarget(address=address, port=port)
        for address in MAC_HOSTS[: settings.node_pool_size]
    ]
    normal_pool = TdxNodePool(
        normal_targets,
        timeout_seconds=settings.normal_node_timeout_seconds,
        failure_threshold=max(settings.node_retry_count, 1),
    )
    enhanced_pool = MacNodePool(
        enhanced_targets,
        timeout_seconds=settings.enhanced_node_timeout_seconds,
        failure_threshold=max(settings.node_retry_count, 1),
    )
    try:
        return probe_tdx_capabilities(normal_pool, enhanced_pool)
    finally:
        normal_pool.close()
        enhanced_pool.close()


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


def _atomic_write_report(output: Path, report: ProviderCapabilities) -> None:
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
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
