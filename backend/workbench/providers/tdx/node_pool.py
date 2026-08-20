from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
import math
import re
import socket
import threading
import time
from typing import Any, Generic, NoReturn, TypeVar, cast

from easy_tdx import TdxConnectionError

from workbench.providers.tdx.clients import (
    AsyncClientFactory,
    AsyncTdxClientProtocol,
    SyncTdxClient,
    create_async_tdx_client,
    create_mac_client,
    create_tdx_client,
)


SyncClientT = TypeVar("SyncClientT", bound=SyncTdxClient)
ResultT = TypeVar("ResultT")
ItemT = TypeVar("ItemT")
ShardResultT = TypeVar("ShardResultT")
Clock = Callable[[], float]
NodeProbe = Callable[["NodeTarget", float], float]
RetryableExceptionClassifier = Callable[[Exception], bool]

_MAX_ERROR_LENGTH = 160
_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:password|passwd|token|secret|api[-_]?key|credentials?)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
    re.IGNORECASE,
)
_URL_CREDENTIAL_PATTERN = re.compile(
    r"\b([a-z][a-z0-9+.-]*://)[^/@\s]+@",
    re.IGNORECASE,
)
_ABSOLUTE_PATH_START_PATTERN = re.compile(
    r'''(?ix)(?<![\w])["']?[a-z]:[\\/]|(?<![:/\w])["']?/'''
)


class PoolLifecycle(str, Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class NodeTarget:
    address: str
    port: int

    def __post_init__(self) -> None:
        address = self.address.strip()
        if not address:
            raise ValueError("node address must not be blank")
        if any(character in address for character in ("@", "/", "\\")):
            raise ValueError("node address must be a host name or IP address")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise TypeError("node port must be an integer")
        if not 1 <= self.port <= 65535:
            raise ValueError("node port must be between 1 and 65535")
        object.__setattr__(self, "address", address)


@dataclass(slots=True)
class NodeState:
    target: NodeTarget
    latency_ms: float | None = None
    consecutive_failures: int = 0
    circuit_open_until: float | None = None
    last_error: str | None = None


class TdxNodePoolError(RuntimeError):
    def __init__(self, pool: str, diagnostics: Sequence[dict[str, object]]) -> None:
        self.pool = pool
        self.diagnostics = [dict(node) for node in diagnostics]
        super().__init__(f"all {pool} TDX nodes are unavailable")


def default_retryable_exception_classifier(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            TdxConnectionError,
            TimeoutError,
            ConnectionError,
            socket.gaierror,
            socket.herror,
            asyncio.IncompleteReadError,
        ),
    )


class _BaseNodePool(Generic[SyncClientT]):
    def __init__(
        self,
        targets: Iterable[NodeTarget],
        *,
        pool_name: str,
        timeout_seconds: float,
        failure_threshold: int,
        cooldown_seconds: float,
        clock: Clock,
        probe: NodeProbe | None,
        client_factory: Callable[[str, int, float], SyncClientT],
        retryable_exception_classifier: RetryableExceptionClassifier,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        _validate_positive_integer("failure_threshold", failure_threshold)
        if not math.isfinite(cooldown_seconds) or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be finite and positive")

        target_list = list(targets)
        if len(set(target_list)) != len(target_list):
            raise ValueError("node targets must be unique")

        self._pool_name = pool_name
        self._timeout_seconds = float(timeout_seconds)
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = float(cooldown_seconds)
        self._clock = clock
        self._probe = probe
        self._states = [NodeState(target=target) for target in target_list]
        self._positions = {state.target: position for position, state in enumerate(self._states)}
        self._client_factory = client_factory
        self._retryable_exception_classifier = retryable_exception_classifier

        self._state_lock = threading.RLock()
        self._sync_operation_lock = threading.RLock()
        self._lifecycle = PoolLifecycle.OPEN
        self._clients: dict[NodeTarget, SyncClientT] = {}
        self._owned_clients: dict[int, SyncClientT] = {}

    @property
    def lifecycle(self) -> PoolLifecycle:
        with self._state_lock:
            return self._lifecycle

    def probe_all(self) -> list[NodeTarget]:
        with self._sync_operation_lock:
            self._ensure_open()
            if self._probe is None:
                raise RuntimeError("no node probe was configured")

            for state in self._states:
                try:
                    latency_ms = float(self._probe(state.target, self._timeout_seconds))
                    if not math.isfinite(latency_ms) or latency_ms < 0:
                        raise ValueError("probe latency must be finite and non-negative")
                except Exception as exc:
                    if not self._is_retryable(exc):
                        raise
                    self._record_failure(state, exc)
                else:
                    self._record_success(state, latency_ms=latency_ms)
            return self.ordered_targets()

    def ordered_targets(self) -> list[NodeTarget]:
        return [state.target for state in self._eligible_states()]

    def execute(self, operation: Callable[[SyncClientT], ResultT]) -> ResultT:
        with self._sync_operation_lock:
            self._ensure_open()
            candidates = self._eligible_states()
            if not candidates:
                self._raise_unavailable(None)

            last_retryable: Exception | None = None
            for state in candidates:
                if not self._is_eligible(state):
                    continue
                try:
                    client = self._client_for(state.target)
                    result = operation(client)
                except Exception as exc:
                    if not self._is_retryable(exc):
                        raise
                    last_retryable = exc
                    self._record_failure(state, exc)
                    self._discard_client(state.target)
                else:
                    self._record_success(state)
                    return result
            self._raise_unavailable(last_retryable)

    def health_snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._state_lock:
            return {
                "pool": self._pool_name,
                "lifecycle": self._lifecycle.value,
                "nodes": [self._node_diagnostic(state, now) for state in self._states],
            }

    def close(self) -> None:
        with self._sync_operation_lock:
            if self.lifecycle is PoolLifecycle.CLOSED:
                return
            self._begin_closing()
            first_error = self._close_all_sync_clients()
            if first_error is not None:
                raise RuntimeError("one or more TDX clients could not be closed") from first_error
            self._mark_closed()

    def __enter__(self) -> _BaseNodePool[SyncClientT]:
        self._ensure_open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def _begin_closing(self) -> None:
        with self._state_lock:
            if self._lifecycle is PoolLifecycle.OPEN:
                self._lifecycle = PoolLifecycle.CLOSING

    def _mark_closed(self) -> None:
        with self._state_lock:
            self._lifecycle = PoolLifecycle.CLOSED

    def _ensure_open(self) -> None:
        with self._state_lock:
            if self._lifecycle is not PoolLifecycle.OPEN:
                raise RuntimeError(f"TDX node pool is {self._lifecycle.value}")

    def _eligible_states(self) -> list[NodeState]:
        now = self._clock()
        with self._state_lock:
            eligible = [state for state in self._states if self._is_eligible_at(state, now)]
            return sorted(
                eligible,
                key=lambda state: (
                    state.latency_ms is None,
                    state.latency_ms if state.latency_ms is not None else 0.0,
                    self._positions[state.target],
                ),
            )

    def _is_eligible(self, state: NodeState) -> bool:
        with self._state_lock:
            return self._is_eligible_at(state, self._clock())

    @staticmethod
    def _is_eligible_at(state: NodeState, now: float) -> bool:
        return state.circuit_open_until is None or now >= state.circuit_open_until

    def _record_success(self, state: NodeState, *, latency_ms: float | None = None) -> None:
        with self._state_lock:
            if latency_ms is not None:
                state.latency_ms = latency_ms
            state.consecutive_failures = 0
            state.circuit_open_until = None
            state.last_error = None

    def _record_failure(self, state: NodeState, exc: Exception) -> None:
        with self._state_lock:
            state.consecutive_failures += 1
            state.last_error = _sanitized_error(exc)
            if state.consecutive_failures >= self._failure_threshold:
                state.circuit_open_until = self._clock() + self._cooldown_seconds

    def _is_retryable(self, exc: Exception) -> bool:
        return bool(self._retryable_exception_classifier(exc))

    def _client_for(self, target: NodeTarget) -> SyncClientT:
        existing = self._clients.get(target)
        if existing is not None:
            return existing

        self._ensure_open()
        client = self._client_factory(target.address, target.port, self._timeout_seconds)
        with self._state_lock:
            self._owned_clients[id(client)] = client
        try:
            client.connect()
        except BaseException:
            self._try_close_sync_client(client)
            raise
        self._clients[target] = client
        return client

    def _discard_client(self, target: NodeTarget) -> None:
        client = self._clients.pop(target, None)
        if client is not None:
            self._try_close_sync_client(client)

    def _try_close_sync_client(self, client: SyncClientT) -> Exception | None:
        try:
            client.close()
        except Exception as exc:
            return exc
        self._release_sync_client(client)
        return None

    def _release_sync_client(self, client: SyncClientT) -> None:
        with self._state_lock:
            self._owned_clients.pop(id(client), None)
            for target, active in list(self._clients.items()):
                if active is client:
                    self._clients.pop(target, None)

    def _close_all_sync_clients(self) -> Exception | None:
        with self._state_lock:
            clients = list(self._owned_clients.values())
        first_error: Exception | None = None
        for client in clients:
            error = self._try_close_sync_client(client)
            if first_error is None and error is not None:
                first_error = error
        return first_error

    def _node_diagnostic(self, state: NodeState, now: float) -> dict[str, object]:
        remaining = (
            max(0.0, state.circuit_open_until - now)
            if state.circuit_open_until is not None
            else 0.0
        )
        return {
            "address": state.target.address,
            "port": state.target.port,
            "latency_ms": state.latency_ms,
            "consecutive_failures": state.consecutive_failures,
            "circuit_open": remaining > 0.0,
            "cooldown_remaining_seconds": remaining,
            "last_error": state.last_error,
        }

    def _unavailable_error(self) -> TdxNodePoolError:
        nodes = cast(list[dict[str, object]], self.health_snapshot()["nodes"])
        return TdxNodePoolError(self._pool_name, nodes)

    def _raise_unavailable(self, cause: Exception | None) -> NoReturn:
        error = self._unavailable_error()
        if cause is None:
            raise error
        raise error from cause


class TdxNodePool(_BaseNodePool[SyncClientT], Generic[SyncClientT]):
    def __init__(
        self,
        targets: Iterable[NodeTarget],
        *,
        timeout_seconds: float,
        failure_threshold: int = 2,
        cooldown_seconds: float = 30.0,
        max_concurrency: int = 8,
        clock: Clock = time.monotonic,
        probe: NodeProbe | None = None,
        client_factory: Callable[[str, int, float], SyncClientT] | None = None,
        async_client_factory: AsyncClientFactory | None = None,
        retryable_exception_classifier: RetryableExceptionClassifier = (
            default_retryable_exception_classifier
        ),
    ) -> None:
        _validate_positive_integer("max_concurrency", max_concurrency)
        super().__init__(
            targets,
            pool_name="normal",
            timeout_seconds=timeout_seconds,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            clock=clock,
            probe=probe,
            client_factory=client_factory
            if client_factory is not None
            else cast(Callable[[str, int, float], SyncClientT], create_tdx_client),
            retryable_exception_classifier=retryable_exception_classifier,
        )
        self._async_client_factory = async_client_factory or create_async_tdx_client
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._async_close_lock = asyncio.Lock()
        self._async_clients: dict[NodeTarget, AsyncTdxClientProtocol] = {}
        self._owned_async_clients: dict[int, AsyncTdxClientProtocol] = {}
        self._node_locks = {state.target: asyncio.Lock() for state in self._states}
        self._batch_tasks: set[asyncio.Task[Any]] = set()
        self._shard_tasks: set[asyncio.Task[Any]] = set()

    async def execute_sharded(
        self,
        items: Iterable[ItemT],
        operation: Callable[[Any, ItemT], Awaitable[ShardResultT]],
    ) -> list[ShardResultT]:
        batch_task = asyncio.current_task()
        if batch_task is None:
            raise RuntimeError("async shard execution requires an asyncio task")
        self._register_batch_task(batch_task)
        shard_tasks: list[asyncio.Task[ShardResultT]] = []
        try:
            item_list = list(items)
            if not item_list:
                return []

            candidates = self._eligible_states()
            if not candidates:
                self._raise_unavailable(None)

            for position, item in enumerate(item_list):
                offset = position % len(candidates)
                ordered = candidates[offset:] + candidates[:offset]
                shard_tasks.append(
                    asyncio.create_task(self._execute_async_on_nodes(ordered, item, operation))
                )
            self._register_shard_tasks(shard_tasks)

            try:
                return list(await asyncio.gather(*shard_tasks))
            except BaseException:
                await _cancel_and_drain(shard_tasks)
                raise
            finally:
                self._unregister_shard_tasks(shard_tasks)
        finally:
            self._unregister_batch_task(batch_task)

    async def aclose(self) -> None:
        async with self._async_close_lock:
            if self.lifecycle is PoolLifecycle.CLOSED:
                return

            with self._sync_operation_lock:
                self._begin_closing()
            await self._cancel_and_await_inflight_work()

            first_error = await self._close_all_async_clients()
            with self._sync_operation_lock:
                sync_error = self._close_all_sync_clients()
            if first_error is None:
                first_error = sync_error
            if first_error is not None:
                raise RuntimeError("one or more TDX clients could not be closed") from first_error
            self._mark_closed()

    def close(self) -> None:
        with self._state_lock:
            has_async_resources = bool(
                self._owned_async_clients or self._batch_tasks or self._shard_tasks
            )
        if not has_async_resources:
            super().close()
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.aclose())
            return
        raise RuntimeError("use 'await pool.aclose()' while an event loop is running")

    async def __aenter__(self) -> TdxNodePool[SyncClientT]:
        self._ensure_open()
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        await self.aclose()

    def _register_batch_task(self, task: asyncio.Task[Any]) -> None:
        with self._state_lock:
            if self._lifecycle is not PoolLifecycle.OPEN:
                raise RuntimeError(f"TDX node pool is {self._lifecycle.value}")
            self._batch_tasks.add(task)

    def _unregister_batch_task(self, task: asyncio.Task[Any]) -> None:
        with self._state_lock:
            self._batch_tasks.discard(task)

    def _register_shard_tasks(self, tasks: Iterable[asyncio.Task[Any]]) -> None:
        with self._state_lock:
            self._shard_tasks.update(tasks)

    def _unregister_shard_tasks(self, tasks: Iterable[asyncio.Task[Any]]) -> None:
        with self._state_lock:
            self._shard_tasks.difference_update(tasks)

    async def _cancel_and_await_inflight_work(self) -> None:
        current = asyncio.current_task()
        with self._state_lock:
            tasks = list((self._batch_tasks | self._shard_tasks) - {current})
        await _cancel_and_drain(tasks)
        with self._state_lock:
            self._batch_tasks.difference_update(task for task in tasks if task.done())
            self._shard_tasks.difference_update(task for task in tasks if task.done())

    async def _execute_async_on_nodes(
        self,
        candidates: Sequence[NodeState],
        item: ItemT,
        operation: Callable[[Any, ItemT], Awaitable[ShardResultT]],
    ) -> ShardResultT:
        last_retryable: Exception | None = None
        for state in candidates:
            self._ensure_open()
            if not self._is_eligible(state):
                continue
            async with self._node_locks[state.target]:
                self._ensure_open()
                if not self._is_eligible(state):
                    continue
                client: AsyncTdxClientProtocol | None = None
                try:
                    async with self._semaphore:
                        self._ensure_open()
                        client = await self._async_client_for(state.target)
                        result = await operation(client, item)
                        self._ensure_open()
                except asyncio.CancelledError:
                    if client is not None:
                        self._evict_async_client(state.target, client)
                        await self._close_async_client_cancellation_safely(client)
                    raise
                except Exception as exc:
                    if not self._is_retryable(exc):
                        raise
                    last_retryable = exc
                    self._record_failure(state, exc)
                    await self._discard_async_client(state.target)
                else:
                    self._record_success(state)
                    return result
        self._raise_unavailable(last_retryable)

    async def _async_client_for(self, target: NodeTarget) -> AsyncTdxClientProtocol:
        self._ensure_open()
        existing = self._async_clients.get(target)
        if existing is not None:
            return existing

        with self._state_lock:
            if self._lifecycle is not PoolLifecycle.OPEN:
                raise RuntimeError(f"TDX node pool is {self._lifecycle.value}")
            client = self._async_client_factory(
                target.address,
                target.port,
                self._timeout_seconds,
            )
            self._owned_async_clients[id(client)] = client
        try:
            await client.connect()
        except asyncio.CancelledError:
            self._evict_async_client(target, client)
            await self._close_async_client_cancellation_safely(client)
            raise
        except Exception:
            await self._try_close_async_client(client)
            raise
        self._ensure_open()
        self._async_clients[target] = client
        return client

    async def _discard_async_client(self, target: NodeTarget) -> None:
        client = self._evict_async_client(target)
        if client is not None:
            await self._try_close_async_client(client)

    def _evict_async_client(
        self,
        target: NodeTarget,
        expected: AsyncTdxClientProtocol | None = None,
    ) -> AsyncTdxClientProtocol | None:
        with self._state_lock:
            client = self._async_clients.get(target)
            if expected is not None and client is not expected:
                return None
            return self._async_clients.pop(target, None)

    async def _close_async_client_cancellation_safely(
        self,
        client: AsyncTdxClientProtocol,
    ) -> None:
        close_task = asyncio.create_task(self._try_close_async_client(client))
        while not close_task.done():
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                continue
        if not close_task.cancelled():
            close_task.exception()

    async def _try_close_async_client(
        self, client: AsyncTdxClientProtocol
    ) -> Exception | None:
        try:
            await client.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return exc
        self._release_async_client(client)
        return None

    def _release_async_client(self, client: AsyncTdxClientProtocol) -> None:
        with self._state_lock:
            self._owned_async_clients.pop(id(client), None)
            for target, active in list(self._async_clients.items()):
                if active is client:
                    self._async_clients.pop(target, None)

    async def _close_all_async_clients(self) -> Exception | None:
        with self._state_lock:
            clients = list(self._owned_async_clients.values())
        first_error: Exception | None = None
        for client in clients:
            error = await self._try_close_async_client(client)
            if first_error is None and error is not None:
                first_error = error
        return first_error


class MacNodePool(_BaseNodePool[SyncClientT], Generic[SyncClientT]):
    def __init__(
        self,
        targets: Iterable[NodeTarget],
        *,
        timeout_seconds: float,
        failure_threshold: int = 2,
        cooldown_seconds: float = 30.0,
        clock: Clock = time.monotonic,
        probe: NodeProbe | None = None,
        client_factory: Callable[[str, int, float], SyncClientT] | None = None,
        retryable_exception_classifier: RetryableExceptionClassifier = (
            default_retryable_exception_classifier
        ),
    ) -> None:
        super().__init__(
            targets,
            pool_name="enhanced",
            timeout_seconds=timeout_seconds,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            clock=clock,
            probe=probe,
            client_factory=client_factory
            if client_factory is not None
            else cast(Callable[[str, int, float], SyncClientT], create_mac_client),
            retryable_exception_classifier=retryable_exception_classifier,
        )


async def _cancel_and_drain(tasks: Iterable[asyncio.Task[Any]]) -> None:
    task_list = list(tasks)
    for task in task_list:
        if not task.done():
            task.cancel()
    if task_list:
        await asyncio.gather(*task_list, return_exceptions=True)


def _validate_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _sanitized_error(exc: Exception) -> str:
    class_name = type(exc).__name__ if type(exc).__name__.isidentifier() else "ProviderError"
    try:
        message = str(exc)
    except Exception:
        message = "error details unavailable"
    message = _URL_CREDENTIAL_PATTERN.sub(r"\1<redacted>@", message)
    message = _CREDENTIAL_PATTERN.sub("<redacted>", message)
    path_start = _ABSOLUTE_PATH_START_PATTERN.search(message)
    if path_start is not None:
        safe_prefix = message[: path_start.start()].rstrip()
        message = f"{safe_prefix} <path redacted>" if safe_prefix else "<path redacted>"
    message = " ".join(message.split())
    summary = f"{class_name}: {message}" if message else class_name
    if len(summary) <= _MAX_ERROR_LENGTH:
        return summary
    return f"{summary[: _MAX_ERROR_LENGTH - 3]}..."
