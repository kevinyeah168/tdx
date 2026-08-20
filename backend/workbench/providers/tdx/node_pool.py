from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
import math
import time
from typing import Any, Generic, TypeVar, cast

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
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if isinstance(failure_threshold, bool) or failure_threshold < 1:
            raise ValueError("failure_threshold must be at least one")
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
        self._clients: dict[NodeTarget, SyncClientT] = {}
        self._created_clients: list[SyncClientT] = []
        self._closed_client_ids: set[int] = set()
        self._closed = False

    def probe_all(self) -> list[NodeTarget]:
        self._ensure_open()
        if self._probe is None:
            raise RuntimeError("no node probe was configured")

        for state in self._states:
            try:
                latency_ms = float(self._probe(state.target, self._timeout_seconds))
                if not math.isfinite(latency_ms) or latency_ms < 0:
                    raise ValueError("probe latency must be finite and non-negative")
            except Exception as exc:
                self._record_failure(state, exc)
            else:
                self._record_success(state, latency_ms=latency_ms)
        return self.ordered_targets()

    def ordered_targets(self) -> list[NodeTarget]:
        return [state.target for state in self._eligible_states()]

    def execute(self, operation: Callable[[SyncClientT], ResultT]) -> ResultT:
        self._ensure_open()
        candidates = self._eligible_states()
        if not candidates:
            raise self._unavailable_error()

        for state in candidates:
            if not self._is_eligible(state):
                continue
            try:
                client = self._client_for(state.target)
                result = operation(client)
            except Exception as exc:
                self._record_failure(state, exc)
                self._discard_client(state.target)
            else:
                self._record_success(state)
                return result
        raise self._unavailable_error()

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "pool": self._pool_name,
            "nodes": [self._node_diagnostic(state) for state in self._states],
        }

    def close(self) -> None:
        if self._closed:
            return
        first_error = self._close_all_sync_clients()
        self._closed = True
        if first_error is not None:
            raise RuntimeError("one or more TDX clients could not be closed") from None

    def __enter__(self) -> _BaseNodePool[SyncClientT]:
        self._ensure_open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("TDX node pool is closed")

    def _eligible_states(self) -> list[NodeState]:
        eligible = [state for state in self._states if self._is_eligible(state)]
        return sorted(
            eligible,
            key=lambda state: (
                state.latency_ms is None,
                state.latency_ms if state.latency_ms is not None else 0.0,
                self._positions[state.target],
            ),
        )

    def _is_eligible(self, state: NodeState) -> bool:
        return state.circuit_open_until is None or self._clock() >= state.circuit_open_until

    def _record_success(self, state: NodeState, *, latency_ms: float | None = None) -> None:
        if latency_ms is not None:
            state.latency_ms = latency_ms
        state.consecutive_failures = 0
        state.circuit_open_until = None
        state.last_error = None

    def _record_failure(self, state: NodeState, exc: Exception) -> None:
        state.consecutive_failures += 1
        state.last_error = _sanitized_error(exc)
        if state.consecutive_failures >= self._failure_threshold:
            state.circuit_open_until = self._clock() + self._cooldown_seconds

    def _client_for(self, target: NodeTarget) -> SyncClientT:
        existing = self._clients.get(target)
        if existing is not None:
            return existing

        client = self._client_factory(target.address, target.port, self._timeout_seconds)
        self._created_clients.append(client)
        try:
            client.connect()
        except Exception:
            self._close_sync_client_once(client)
            raise
        self._clients[target] = client
        return client

    def _discard_client(self, target: NodeTarget) -> None:
        client = self._clients.pop(target, None)
        if client is not None:
            self._close_sync_client_once(client)

    def _close_sync_client_once(self, client: SyncClientT) -> Exception | None:
        client_id = id(client)
        if client_id in self._closed_client_ids:
            return None
        self._closed_client_ids.add(client_id)
        try:
            client.close()
        except Exception as exc:
            return exc
        return None

    def _close_all_sync_clients(self) -> Exception | None:
        first_error: Exception | None = None
        for client in self._created_clients:
            error = self._close_sync_client_once(client)
            if first_error is None and error is not None:
                first_error = error
        self._clients.clear()
        return first_error

    def _node_diagnostic(self, state: NodeState) -> dict[str, object]:
        return {
            "address": state.target.address,
            "port": state.target.port,
            "latency_ms": state.latency_ms,
            "consecutive_failures": state.consecutive_failures,
            "circuit_open_until": state.circuit_open_until,
            "last_error": state.last_error,
        }

    def _unavailable_error(self) -> TdxNodePoolError:
        nodes = cast(list[dict[str, object]], self.health_snapshot()["nodes"])
        return TdxNodePoolError(self._pool_name, nodes)


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
    ) -> None:
        if isinstance(max_concurrency, bool) or max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
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
        )
        self._async_client_factory = async_client_factory or create_async_tdx_client
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._async_clients: dict[NodeTarget, AsyncTdxClientProtocol] = {}
        self._created_async_clients: list[AsyncTdxClientProtocol] = []
        self._closed_async_client_ids: set[int] = set()
        self._node_locks = {state.target: asyncio.Lock() for state in self._states}

    async def execute_sharded(
        self,
        items: Iterable[ItemT],
        operation: Callable[[Any, ItemT], Awaitable[ShardResultT]],
    ) -> list[ShardResultT]:
        self._ensure_open()
        item_list = list(items)
        if not item_list:
            return []

        candidates = self._eligible_states()
        if not candidates:
            raise self._unavailable_error()

        async def execute_one(position: int, item: ItemT) -> ShardResultT:
            offset = position % len(candidates)
            ordered = candidates[offset:] + candidates[:offset]
            return await self._execute_async_on_nodes(ordered, item, operation)

        return list(
            await asyncio.gather(
                *(execute_one(position, item) for position, item in enumerate(item_list))
            )
        )

    async def aclose(self) -> None:
        if self._closed:
            return

        first_error: Exception | None = None
        for client in self._created_async_clients:
            error = await self._close_async_client_once(client)
            if first_error is None and error is not None:
                first_error = error
        self._async_clients.clear()

        sync_error = self._close_all_sync_clients()
        if first_error is None:
            first_error = sync_error
        self._closed = True
        if first_error is not None:
            raise RuntimeError("one or more TDX clients could not be closed") from None

    def close(self) -> None:
        if self._closed:
            return
        has_open_async_clients = any(
            id(client) not in self._closed_async_client_ids for client in self._created_async_clients
        )
        if not has_open_async_clients:
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

    async def _execute_async_on_nodes(
        self,
        candidates: Sequence[NodeState],
        item: ItemT,
        operation: Callable[[Any, ItemT], Awaitable[ShardResultT]],
    ) -> ShardResultT:
        for state in candidates:
            if not self._is_eligible(state):
                continue
            async with self._node_locks[state.target]:
                if not self._is_eligible(state):
                    continue
                try:
                    async with self._semaphore:
                        client = await self._async_client_for(state.target)
                        result = await operation(client, item)
                except Exception as exc:
                    self._record_failure(state, exc)
                    await self._discard_async_client(state.target)
                else:
                    self._record_success(state)
                    return result
        raise self._unavailable_error()

    async def _async_client_for(self, target: NodeTarget) -> AsyncTdxClientProtocol:
        existing = self._async_clients.get(target)
        if existing is not None:
            return existing

        client = self._async_client_factory(target.address, target.port, self._timeout_seconds)
        self._created_async_clients.append(client)
        try:
            await client.connect()
        except Exception:
            await self._close_async_client_once(client)
            raise
        self._async_clients[target] = client
        return client

    async def _discard_async_client(self, target: NodeTarget) -> None:
        client = self._async_clients.pop(target, None)
        if client is not None:
            await self._close_async_client_once(client)

    async def _close_async_client_once(
        self, client: AsyncTdxClientProtocol
    ) -> Exception | None:
        client_id = id(client)
        if client_id in self._closed_async_client_ids:
            return None
        self._closed_async_client_ids.add(client_id)
        try:
            await client.close()
        except Exception as exc:
            return exc
        return None


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
        )


def _sanitized_error(exc: Exception) -> str:
    name = type(exc).__name__
    if not name.isidentifier():
        return "ProviderError"
    return name
