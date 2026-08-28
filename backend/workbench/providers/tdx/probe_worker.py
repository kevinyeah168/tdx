from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
import time
from typing import Literal, Protocol, TypeVar, cast

from easy_tdx import BoardType, KlineCategory, Market, Period

from workbench.providers.tdx.clients import (
    EnhancedProbeClient,
    NormalProbeClient,
    get_security_list_all_network,
)
from workbench.providers.tdx.node_pool import MacNodePool, NodeTarget, TdxNodePool
from workbench.providers.tdx.probe_validation import sanitized_error


PoolKind = Literal["normal", "enhanced"]
OperationName = Literal[
    "security-catalog",
    "board-list",
    "board-members",
    "official-funds",
    "normal-quotes",
    "enhanced-quotes",
    "transactions",
    "minute-data",
    "normal-bars",
    "enhanced-bars",
    "normal-order-book",
    "enhanced-order-book",
]

_STOCK_CODE = "600000"
_NORMAL_MARKET = Market.SH
_ENHANCED_MARKET = int(Market.SH)
_SAMPLE_COUNT = 3
_BOARD_SAMPLE_COUNT = 8

ResultT = TypeVar("ResultT")


class SourceExecutor(Protocol):
    def execute(
        self,
        request: "SourceRequest",
        *,
        source: str,
        hard_timeout_seconds: float,
    ) -> object: ...


class InlinePool(Protocol):
    def execute(self, operation: Callable[[object], ResultT]) -> ResultT: ...


class SourceHardDeadlineExceeded(TimeoutError):
    pass


class RemoteSourceError(RuntimeError):
    pass


class SourceWorkerCleanupError(RuntimeError):
    pass


class LivePoolCleanupError(RuntimeError):
    def __init__(self, errors: list[BaseException]) -> None:
        self.errors = tuple(errors)
        super().__init__(f"{len(errors)} live TDX pool cleanup operation(s) failed")


@dataclass(frozen=True, slots=True)
class SourceRequest:
    pool: PoolKind
    operation: OperationName
    board_id: str | None = None
    fields: object = None


@dataclass(frozen=True, slots=True)
class LiveSourceExecutorConfig:
    normal_targets: tuple[NodeTarget, ...]
    enhanced_targets: tuple[NodeTarget, ...]
    socket_timeout_seconds: float
    failure_threshold: int

    def __post_init__(self) -> None:
        if not self.normal_targets or not self.enhanced_targets:
            raise ValueError("live source executor requires normal and enhanced targets")
        if (
            not math.isfinite(self.socket_timeout_seconds)
            or self.socket_timeout_seconds <= 0
        ):
            raise ValueError("socket_timeout_seconds must be finite and positive")
        if (
            isinstance(self.failure_threshold, bool)
            or self.failure_threshold <= 0
        ):
            raise ValueError("failure_threshold must be a positive integer")


class ProcessWatchdog:
    """Run one blocking call in a disposable process with a wall-clock timeout."""

    def __init__(self, *, termination_grace_seconds: float = 0.1) -> None:
        if (
            not math.isfinite(termination_grace_seconds)
            or termination_grace_seconds <= 0
        ):
            raise ValueError("termination_grace_seconds must be finite and positive")
        self._termination_grace_seconds = termination_grace_seconds
        self._context = multiprocessing.get_context("spawn")
        self.last_worker_pid: int | None = None
        self.last_worker_exitcode: int | None = None

    def call(
        self,
        operation: Callable[..., ResultT],
        args: tuple[object, ...],
        *,
        source: str,
        hard_timeout_seconds: float,
    ) -> ResultT:
        if not math.isfinite(hard_timeout_seconds) or hard_timeout_seconds <= 0:
            raise ValueError("hard_timeout_seconds must be finite and positive")

        receiver, sender = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_watchdog_child,
            args=(sender, operation, args),
            name="tdx-probe-source",
        )
        started = time.monotonic()
        try:
            process.start()
            self.last_worker_pid = process.pid
            sender.close()
            remaining = hard_timeout_seconds - (time.monotonic() - started)
            if remaining <= 0 or not receiver.poll(remaining):
                self._terminate_and_reap(process)
                raise SourceHardDeadlineExceeded(
                    "source call exceeded its wall-clock hard deadline"
                )

            try:
                status, payload = cast(tuple[str, object], receiver.recv())
            except EOFError as exc:
                self._reap_completed_worker(process)
                raise RemoteSourceError(f"{source} worker exited without a result") from exc

            self._reap_completed_worker(process)
            if status == "error":
                raise RemoteSourceError(str(payload))
            if status != "ok":
                raise RemoteSourceError(f"{source} worker returned an invalid envelope")
            return cast(ResultT, payload)
        finally:
            receiver.close()
            sender.close()
            if process.pid is not None and process.is_alive():
                self._terminate_and_reap(process)
            self.last_worker_exitcode = process.exitcode

    def _reap_completed_worker(self, process: BaseProcess) -> None:
        process.join(max(self._termination_grace_seconds, 2.0))
        if process.is_alive():
            self._terminate_and_reap(process)
            raise SourceWorkerCleanupError(
                "source worker did not exit after returning its result"
            )

    def _terminate_and_reap(self, process: BaseProcess) -> None:
        if process.is_alive():
            process.terminate()
        process.join(self._termination_grace_seconds)
        if process.is_alive():
            process.kill()
            process.join(self._termination_grace_seconds)
        if process.is_alive():
            raise SourceWorkerCleanupError(
                "source worker could not be reaped within the termination grace"
            )


class ProcessSourceExecutor:
    def __init__(
        self,
        config: LiveSourceExecutorConfig,
        *,
        termination_grace_seconds: float = 0.1,
    ) -> None:
        self._config = config
        self._watchdog = ProcessWatchdog(
            termination_grace_seconds=termination_grace_seconds
        )

    def execute(
        self,
        request: SourceRequest,
        *,
        source: str,
        hard_timeout_seconds: float,
    ) -> object:
        return self._watchdog.call(
            _execute_live_source,
            (self._config, request),
            source=source,
            hard_timeout_seconds=hard_timeout_seconds,
        )


class InlineTestSourceExecutor:
    """Transport-free executor for deterministic tests; it is not a hard boundary."""

    def __init__(self, normal_pool: InlinePool, enhanced_pool: InlinePool) -> None:
        self._normal_pool = normal_pool
        self._enhanced_pool = enhanced_pool

    def execute(
        self,
        request: SourceRequest,
        *,
        source: str,
        hard_timeout_seconds: float,
    ) -> object:
        del source, hard_timeout_seconds
        selected_pool = (
            self._normal_pool if request.pool == "normal" else self._enhanced_pool
        )
        return selected_pool.execute(
            lambda client: execute_request_on_client(client, request)
        )


def execute_request_on_client(client: object, request: SourceRequest) -> object:
    if request.operation == "security-catalog":
        return get_security_list_all_network(client)  # type: ignore[arg-type]
    if request.operation == "board-list":
        return client.get_board_list(  # type: ignore[attr-defined]
            board_type=BoardType.HY,
            count=_BOARD_SAMPLE_COUNT,
        )
    if request.operation == "board-members":
        if not request.board_id:
            raise ValueError("board-members request requires a board id")
        return client.get_board_members(  # type: ignore[attr-defined]
            request.board_id,
            count=_SAMPLE_COUNT,
        )
    if request.operation == "official-funds":
        return client.get_capital_flow(  # type: ignore[attr-defined]
            _ENHANCED_MARKET,
            _STOCK_CODE,
        )
    if request.operation in {"normal-quotes", "normal-order-book"}:
        return client.get_security_quotes(  # type: ignore[attr-defined]
            [(_NORMAL_MARKET, _STOCK_CODE)]
        )
    if request.operation in {"enhanced-quotes", "enhanced-order-book"}:
        return client.get_stock_quotes(  # type: ignore[attr-defined]
            [(_ENHANCED_MARKET, _STOCK_CODE)],
            fields=request.fields,
        )
    if request.operation == "transactions":
        return client.get_transaction_data(  # type: ignore[attr-defined]
            _NORMAL_MARKET,
            _STOCK_CODE,
            0,
            _SAMPLE_COUNT,
        )
    if request.operation == "minute-data":
        return client.get_minute_time_data(  # type: ignore[attr-defined]
            _NORMAL_MARKET,
            _STOCK_CODE,
        )
    if request.operation == "normal-bars":
        return client.get_security_bars(  # type: ignore[attr-defined]
            _NORMAL_MARKET,
            _STOCK_CODE,
            KlineCategory.DAY,
            0,
            _SAMPLE_COUNT,
        )
    if request.operation == "enhanced-bars":
        return client.get_stock_kline(  # type: ignore[attr-defined]
            _ENHANCED_MARKET,
            _STOCK_CODE,
            Period.DAILY,
            0,
            _SAMPLE_COUNT,
        )
    raise ValueError(f"unsupported TDX probe operation: {request.operation}")


def _watchdog_child(
    sender: Connection,
    operation: Callable[..., object],
    args: tuple[object, ...],
) -> None:
    try:
        try:
            result = operation(*args)
        except BaseException as exc:
            envelope: tuple[str, object] = ("error", sanitized_error(exc))
        else:
            envelope = ("ok", result)
        sender.send(envelope)
    finally:
        sender.close()


def _execute_live_source(
    config: LiveSourceExecutorConfig,
    request: SourceRequest,
) -> object:
    normal_pool: TdxNodePool[NormalProbeClient] = TdxNodePool(
        config.normal_targets,
        timeout_seconds=config.socket_timeout_seconds,
        failure_threshold=config.failure_threshold,
    )
    try:
        enhanced_pool: MacNodePool[EnhancedProbeClient] = MacNodePool(
            config.enhanced_targets,
            timeout_seconds=config.socket_timeout_seconds,
            failure_threshold=config.failure_threshold,
        )
    except BaseException:
        normal_pool.close()
        raise

    try:
        selected_pool = normal_pool if request.pool == "normal" else enhanced_pool
        result = selected_pool.execute(
            lambda client: execute_request_on_client(client, request)
        )
    except BaseException as primary:
        try:
            _close_live_pools(normal_pool, enhanced_pool)
        except LivePoolCleanupError as cleanup:
            raise primary from cleanup
        raise
    _close_live_pools(normal_pool, enhanced_pool)
    return result


def _close_live_pools(normal_pool: object, enhanced_pool: object) -> None:
    errors: list[BaseException] = []
    for pool in (normal_pool, enhanced_pool):
        try:
            pool.close()  # type: ignore[attr-defined]
        except BaseException as exc:
            errors.append(exc)
    if errors:
        raise LivePoolCleanupError(errors)
