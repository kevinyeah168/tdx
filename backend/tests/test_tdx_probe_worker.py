from __future__ import annotations

import multiprocessing
import time

import pytest

from workbench.providers.tdx import probe_worker
from workbench.providers.tdx.node_pool import NodeTarget
from workbench.providers.tdx.probe_worker import (
    LivePoolCleanupError,
    LiveSourceExecutorConfig,
    ProcessWatchdog,
    SourceRequest,
    SourceHardDeadlineExceeded,
)


def blocking_catalog_call(delay_seconds: float) -> str:
    time.sleep(delay_seconds)
    return "cached-looking-success"


def test_process_watchdog_enforces_wall_clock_bound_and_reaps_blocked_worker() -> None:
    before = {child.pid for child in multiprocessing.active_children()}
    watchdog = ProcessWatchdog(termination_grace_seconds=0.05)
    started = time.monotonic()

    with pytest.raises(SourceHardDeadlineExceeded, match="wall-clock hard deadline"):
        watchdog.call(
            blocking_catalog_call,
            (0.5,),
            source="tdx.normal.security-list-all-network",
            hard_timeout_seconds=0.05,
        )

    elapsed = time.monotonic() - started
    assert elapsed < 0.4
    assert watchdog.last_worker_pid is not None
    assert watchdog.last_worker_exitcode is not None
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_process_watchdog_returns_fast_source_result() -> None:
    watchdog = ProcessWatchdog(termination_grace_seconds=0.05)

    result = watchdog.call(
        blocking_catalog_call,
        (0.0,),
        source="tdx.normal.security-list-all-network",
        hard_timeout_seconds=5.0,
    )

    assert result == "cached-looking-success"
    assert watchdog.last_worker_exitcode == 0


class ClosingPool:
    def __init__(
        self,
        label: str,
        events: list[str],
        *,
        close_fails: bool = False,
        execute_error: BaseException | None = None,
    ) -> None:
        self.label = label
        self.events = events
        self.close_fails = close_fails
        self.execute_error = execute_error

    def execute(self, _operation: object) -> object:
        if self.execute_error is not None:
            raise self.execute_error
        return []

    def close(self) -> None:
        self.events.append(self.label)
        if self.close_fails:
            raise RuntimeError(f"{self.label} close failed")


def test_normal_close_failure_still_closes_enhanced() -> None:
    events: list[str] = []

    with pytest.raises(LivePoolCleanupError) as captured:
        probe_worker._close_live_pools(
            ClosingPool("normal", events, close_fails=True),
            ClosingPool("enhanced", events),
        )

    assert events == ["normal", "enhanced"]
    assert len(captured.value.errors) == 1


def test_both_live_pool_close_failures_are_reported_together() -> None:
    events: list[str] = []

    with pytest.raises(LivePoolCleanupError) as captured:
        probe_worker._close_live_pools(
            ClosingPool("normal", events, close_fails=True),
            ClosingPool("enhanced", events, close_fails=True),
        )

    assert events == ["normal", "enhanced"]
    assert len(captured.value.errors) == 2


def test_primary_source_exception_is_preserved_and_cleanup_failures_are_chained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    primary = RuntimeError("primary source failure")
    normal = ClosingPool(
        "normal",
        events,
        close_fails=True,
        execute_error=primary,
    )
    enhanced = ClosingPool("enhanced", events, close_fails=True)
    monkeypatch.setattr(probe_worker, "TdxNodePool", lambda *_args, **_kwargs: normal)
    monkeypatch.setattr(probe_worker, "MacNodePool", lambda *_args, **_kwargs: enhanced)
    target = NodeTarget("contract.invalid", 7709)
    config = LiveSourceExecutorConfig(
        normal_targets=(target,),
        enhanced_targets=(target,),
        socket_timeout_seconds=0.1,
        failure_threshold=1,
    )

    with pytest.raises(RuntimeError, match="primary source failure") as captured:
        probe_worker._execute_live_source(
            config,
            SourceRequest(pool="normal", operation="normal-quotes"),
        )

    assert captured.value is primary
    assert events == ["normal", "enhanced"]
    assert isinstance(captured.value.__cause__, LivePoolCleanupError)
    assert len(captured.value.__cause__.errors) == 2
