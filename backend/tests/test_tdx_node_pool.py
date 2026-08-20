from __future__ import annotations

import asyncio
import gc
import json
from pathlib import Path
from typing import Any, Callable
import weakref

import pytest

from workbench.providers.tdx.node_pool import (
    MacNodePool,
    NodeTarget,
    TdxNodePool,
    TdxNodePoolError,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tdx" / "nodes.json"


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSyncClient:
    def __init__(self, address: str, port: int, timeout: float) -> None:
        self.address = address
        self.port = port
        self.timeout = timeout
        self.connect_calls = 0
        self.close_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class FakeSyncFactory:
    def __init__(self) -> None:
        self.clients: list[FakeSyncClient] = []

    def __call__(self, address: str, port: int, timeout: float) -> FakeSyncClient:
        client = FakeSyncClient(address, port, timeout)
        self.clients.append(client)
        return client


class FakeAsyncClient:
    def __init__(self, address: str, port: int, timeout: float) -> None:
        self.address = address
        self.port = port
        self.timeout = timeout
        self.connect_calls = 0
        self.close_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class FakeAsyncFactory:
    def __init__(self) -> None:
        self.clients: list[FakeAsyncClient] = []

    def __call__(self, address: str, port: int, timeout: float) -> FakeAsyncClient:
        client = FakeAsyncClient(address, port, timeout)
        self.clients.append(client)
        return client


class ConcurrencyTracker:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0

    async def run(self) -> None:
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.active -= 1


class FakeTransportError(ConnectionError):
    pass


class ReviewTransportError(RuntimeError):
    pass


class FatalShardError(BaseException):
    pass


def load_targets(kind: str) -> list[NodeTarget]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return [NodeTarget(**node) for node in payload[kind]]


def node_snapshot(pool: TdxNodePool[Any] | MacNodePool[Any], address: str) -> dict[str, Any]:
    return next(node for node in pool.health_snapshot()["nodes"] if node["address"] == address)


def test_probe_latency_orders_normal_nodes_deterministically() -> None:
    targets = load_targets("normal")
    latencies = {
        "10.0.0.1": 42.0,
        "10.0.0.2": 8.5,
        "10.0.0.3": 21.0,
    }
    probe_calls: list[tuple[NodeTarget, float]] = []

    def probe(target: NodeTarget, timeout: float) -> float:
        probe_calls.append((target, timeout))
        return latencies[target.address]

    pool = TdxNodePool(
        targets,
        timeout_seconds=1.25,
        probe=probe,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
    )

    pool.probe_all()

    assert pool.ordered_targets() == [targets[1], targets[2], targets[0]]
    assert probe_calls == [(target, 1.25) for target in targets]
    assert [node["latency_ms"] for node in pool.health_snapshot()["nodes"]] == [
        42.0,
        8.5,
        21.0,
    ]


def test_first_node_failure_transparently_switches_to_next_healthy_node() -> None:
    targets = load_targets("normal")[:2]
    attempts: list[str] = []
    factory = FakeSyncFactory()
    pool = TdxNodePool(
        targets,
        timeout_seconds=2.0,
        failure_threshold=3,
        client_factory=factory,
        async_client_factory=FakeAsyncFactory(),
    )

    def operation(client: FakeSyncClient) -> str:
        attempts.append(client.address)
        if client.address == targets[0].address:
            raise ConnectionError("first node is down")
        return "quotes"

    assert pool.execute(operation) == "quotes"
    assert attempts == [targets[0].address, targets[1].address]
    assert node_snapshot(pool, targets[0].address)["consecutive_failures"] == 1
    assert node_snapshot(pool, targets[1].address)["consecutive_failures"] == 0
    assert [client.connect_calls for client in factory.clients] == [1, 1]


def test_consecutive_failures_open_circuit_and_do_not_retry_same_node_forever() -> None:
    target = load_targets("normal")[0]
    attempts = 0
    clock = FakeClock()
    pool = TdxNodePool(
        [target],
        timeout_seconds=1.0,
        failure_threshold=2,
        cooldown_seconds=30.0,
        clock=clock,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
    )

    def fail(_client: FakeSyncClient) -> None:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("node timeout")

    with pytest.raises(TdxNodePoolError):
        pool.execute(fail)
    with pytest.raises(TdxNodePoolError):
        pool.execute(fail)
    with pytest.raises(TdxNodePoolError):
        pool.execute(fail)

    state = node_snapshot(pool, target.address)
    assert attempts == 2
    assert state["consecutive_failures"] == 2
    assert state["circuit_open"] is True
    assert state["cooldown_remaining_seconds"] == 30.0


def test_node_is_eligible_after_cooldown_and_success_resets_failure_state() -> None:
    target = load_targets("normal")[0]
    clock = FakeClock()
    attempts: list[str] = []
    pool = TdxNodePool(
        [target],
        timeout_seconds=1.0,
        failure_threshold=1,
        cooldown_seconds=30.0,
        clock=clock,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
    )

    def fail(client: FakeSyncClient) -> None:
        attempts.append(client.address)
        raise ConnectionError("temporarily unavailable")

    with pytest.raises(TdxNodePoolError):
        pool.execute(fail)
    clock.advance(29.0)
    with pytest.raises(TdxNodePoolError):
        pool.execute(lambda client: attempts.append(client.address))
    clock.advance(1.0)

    assert pool.execute(lambda client: (attempts.append(client.address), "ok")[1]) == "ok"
    state = node_snapshot(pool, target.address)
    assert attempts == [target.address, target.address]
    assert state["consecutive_failures"] == 0
    assert state["circuit_open"] is False
    assert state["cooldown_remaining_seconds"] == 0.0
    assert state["last_error"] is None


def test_context_manager_and_explicit_close_disconnect_every_created_client_once() -> None:
    targets = load_targets("normal")[:2]
    normal_factory = FakeSyncFactory()

    with TdxNodePool(
        targets,
        timeout_seconds=1.0,
        client_factory=normal_factory,
        async_client_factory=FakeAsyncFactory(),
    ) as normal_pool:
        assert normal_pool.execute(
            lambda client: (_ for _ in ()).throw(ConnectionError("down"))
            if client.address == targets[0].address
            else "ok"
        ) == "ok"

    normal_pool.close()
    assert len(normal_factory.clients) == 2
    assert [client.close_calls for client in normal_factory.clients] == [1, 1]

    enhanced_factory = FakeSyncFactory()
    enhanced_pool = MacNodePool(
        load_targets("enhanced")[:1],
        timeout_seconds=1.0,
        client_factory=enhanced_factory,
    )
    assert enhanced_pool.execute(lambda _client: "ok") == "ok"
    enhanced_pool.close()
    enhanced_pool.close()
    assert [client.close_calls for client in enhanced_factory.clients] == [1]


def test_normal_and_enhanced_pools_never_share_health_or_failure_state() -> None:
    shared_target = NodeTarget(address="10.9.0.1", port=7709)
    normal_pool = TdxNodePool(
        [shared_target],
        timeout_seconds=1.0,
        failure_threshold=1,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
    )
    enhanced_pool = MacNodePool(
        [shared_target],
        timeout_seconds=1.0,
        failure_threshold=1,
        client_factory=FakeSyncFactory(),
    )

    with pytest.raises(TdxNodePoolError):
        normal_pool.execute(lambda _client: (_ for _ in ()).throw(ConnectionError("normal down")))

    assert enhanced_pool.execute(lambda _client: "enhanced ok") == "enhanced ok"
    assert node_snapshot(normal_pool, shared_target.address)["consecutive_failures"] == 1
    assert node_snapshot(enhanced_pool, shared_target.address)["consecutive_failures"] == 0
    assert node_snapshot(enhanced_pool, shared_target.address)["circuit_open"] is False


def test_async_normal_work_is_stably_sharded_with_total_concurrency_ceiling() -> None:
    async def exercise() -> None:
        targets = load_targets("normal")
        latencies = {targets[0].address: 30.0, targets[1].address: 10.0, targets[2].address: 20.0}
        factory = FakeAsyncFactory()
        tracker = ConcurrencyTracker()
        pool = TdxNodePool(
            targets,
            timeout_seconds=1.0,
            probe=lambda target, _timeout: latencies[target.address],
            client_factory=FakeSyncFactory(),
            async_client_factory=factory,
            max_concurrency=2,
        )
        pool.probe_all()

        async def operation(client: FakeAsyncClient, item: int) -> tuple[int, str]:
            await tracker.run()
            return item, client.address

        results = await pool.execute_sharded(range(6), operation)

        assert results == [
            (0, targets[1].address),
            (1, targets[2].address),
            (2, targets[0].address),
            (3, targets[1].address),
            (4, targets[2].address),
            (5, targets[0].address),
        ]
        assert tracker.maximum == 2
        assert len(factory.clients) == 3
        assert [client.connect_calls for client in factory.clients] == [1, 1, 1]

        await pool.aclose()
        await pool.aclose()
        assert [client.close_calls for client in factory.clients] == [1, 1, 1]

    asyncio.run(exercise())


def test_all_nodes_unavailable_raises_one_controlled_error_with_sanitized_diagnostics() -> None:
    targets = load_targets("normal")[:2]
    clock = FakeClock()
    attempts: list[str] = []
    errors: list[ReviewTransportError] = []
    pool = TdxNodePool(
        targets,
        timeout_seconds=1.0,
        failure_threshold=1,
        cooldown_seconds=45.0,
        clock=clock,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
        retryable_exception_classifier=lambda exc: isinstance(exc, ReviewTransportError),
    )

    def leak_prone_failure(client: FakeSyncClient) -> None:
        attempts.append(client.address)
        error = ReviewTransportError(
            r"connection rejected password=hunter2 token=abcd C:\Users\alice\private\nodes.json"
        )
        errors.append(error)
        raise error

    with pytest.raises(TdxNodePoolError) as raised:
        pool.execute(leak_prone_failure)

    assert str(raised.value) == "all normal TDX nodes are unavailable"
    assert attempts == [target.address for target in targets]
    assert raised.value.diagnostics == pool.health_snapshot()["nodes"]
    assert raised.value.__cause__ is errors[-1]

    serialized = json.dumps(pool.health_snapshot(), sort_keys=True)
    assert "hunter2" not in serialized
    assert "abcd" not in serialized
    assert "C:" not in serialized
    assert "Users" not in serialized
    assert "nodes.json" not in serialized
    assert "ReviewTransportError: connection rejected" in serialized
    assert all(len(str(node["last_error"])) <= 160 for node in pool.health_snapshot()["nodes"])


def test_health_snapshot_is_json_serializable_and_has_only_controlled_node_fields() -> None:
    target = load_targets("normal")[0]
    clock = FakeClock()
    pool = TdxNodePool(
        [target],
        timeout_seconds=1.0,
        failure_threshold=1,
        cooldown_seconds=15.0,
        clock=clock,
        probe=lambda _target, _timeout: 12.5,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
    )
    pool.probe_all()

    with pytest.raises(TdxNodePoolError):
        pool.execute(lambda _client: (_ for _ in ()).throw(OSError("safe summary")))

    snapshot = pool.health_snapshot()
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert snapshot["pool"] == "normal"
    assert set(snapshot["nodes"][0]) == {
        "address",
        "port",
        "latency_ms",
        "consecutive_failures",
        "circuit_open",
        "cooldown_remaining_seconds",
        "last_error",
    }
    assert snapshot["nodes"][0] == {
        "address": target.address,
        "port": target.port,
        "latency_ms": 12.5,
        "consecutive_failures": 1,
        "circuit_open": True,
        "cooldown_remaining_seconds": 15.0,
        "last_error": "OSError: safe summary",
    }
    clock.advance(5.0)
    assert node_snapshot(pool, target.address)["cooldown_remaining_seconds"] == 10.0
    assert "credentials" not in snapshot
    assert "traceback" not in snapshot


def test_async_batch_cancels_and_awaits_siblings_before_propagating_failure() -> None:
    async def exercise() -> None:
        sibling_started = asyncio.Event()
        sibling_cancelled = asyncio.Event()
        release_sibling = asyncio.Event()
        completions: list[int] = []
        pool = TdxNodePool(
            load_targets("normal")[:2],
            timeout_seconds=1.0,
            max_concurrency=2,
            client_factory=FakeSyncFactory(),
            async_client_factory=FakeAsyncFactory(),
        )

        async def operation(_client: FakeAsyncClient, item: int) -> int:
            if item == 0:
                await sibling_started.wait()
                raise FatalShardError("shard terminated")
            sibling_started.set()
            try:
                await release_sibling.wait()
            except asyncio.CancelledError:
                sibling_cancelled.set()
                raise
            completions.append(item)
            return item

        try:
            with pytest.raises(FatalShardError, match="shard terminated"):
                await pool.execute_sharded([0, 1], operation)
            assert sibling_cancelled.is_set()
            assert completions == []
            await asyncio.sleep(0)
            assert completions == []
        finally:
            release_sibling.set()
            await asyncio.sleep(0)
            await pool.aclose()

    asyncio.run(exercise())


def test_aclose_cancels_and_awaits_work_before_closing_pool() -> None:
    async def exercise() -> None:
        operation_started = asyncio.Event()
        operation_cancelled = asyncio.Event()
        release_operation = asyncio.Event()
        completions: list[int] = []
        factory = FakeAsyncFactory()
        pool = TdxNodePool(
            load_targets("normal")[:1],
            timeout_seconds=1.0,
            max_concurrency=1,
            client_factory=FakeSyncFactory(),
            async_client_factory=factory,
        )

        async def operation(_client: FakeAsyncClient, item: int) -> int:
            operation_started.set()
            try:
                await release_operation.wait()
            except asyncio.CancelledError:
                operation_cancelled.set()
                raise
            completions.append(item)
            return item

        batch = asyncio.create_task(pool.execute_sharded([0, 1], operation))
        await operation_started.wait()
        close_task = asyncio.create_task(pool.aclose())
        await asyncio.sleep(0)
        try:
            with pytest.raises(RuntimeError, match="closing|closed"):
                await pool.execute_sharded([2], operation)
            await close_task
            assert batch.done()
            with pytest.raises(asyncio.CancelledError):
                await batch
            assert operation_cancelled.is_set()
            assert completions == []
            assert len(factory.clients) == 1
            assert factory.clients[0].close_calls == 1
        finally:
            release_operation.set()
            if not batch.done():
                batch.cancel()
            await asyncio.gather(batch, return_exceptions=True)
            if not close_task.done():
                close_task.cancel()
            await asyncio.gather(close_task, return_exceptions=True)

    asyncio.run(exercise())


def test_cancelled_connect_remains_owned_until_aclose_cleans_it_up() -> None:
    async def exercise() -> None:
        async def cancel_connect_and_close() -> tuple[TdxNodePool[Any], int]:
            connect_started = asyncio.Event()
            connect_release = asyncio.Event()

            class BlockingConnectClient(FakeAsyncClient):
                async def connect(self) -> None:
                    self.connect_calls += 1
                    connect_started.set()
                    await connect_release.wait()

            clients: list[BlockingConnectClient] = []

            def factory(address: str, port: int, timeout: float) -> BlockingConnectClient:
                client = BlockingConnectClient(address, port, timeout)
                clients.append(client)
                return client

            pool = TdxNodePool(
                load_targets("normal")[:1],
                timeout_seconds=1.0,
                client_factory=FakeSyncFactory(),
                async_client_factory=factory,
            )
            task = asyncio.create_task(pool.execute_sharded([1], lambda _client, item: item))
            await connect_started.wait()
            client = clients[0]
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            await pool.aclose()
            close_calls = client.close_calls
            clients.clear()
            return pool, close_calls

        pool, close_calls = await cancel_connect_and_close()
        assert close_calls == 1
        assert pool.health_snapshot()["lifecycle"] == "closed"

    asyncio.run(exercise())


@pytest.mark.parametrize("first_close", ["cancel", "raise"])
def test_aclose_retries_clients_after_cancellation_or_close_error(first_close: str) -> None:
    async def exercise() -> None:
        close_started = asyncio.Event()
        close_release = asyncio.Event()

        class RetryCloseClient(FakeAsyncClient):
            async def close(self) -> None:
                self.close_calls += 1
                if self.close_calls != 1:
                    return
                if first_close == "raise":
                    raise OSError("close failed")
                close_started.set()
                await close_release.wait()

        clients: list[RetryCloseClient] = []

        def factory(address: str, port: int, timeout: float) -> RetryCloseClient:
            client = RetryCloseClient(address, port, timeout)
            clients.append(client)
            return client

        pool = TdxNodePool(
            load_targets("normal")[:1],
            timeout_seconds=1.0,
            client_factory=FakeSyncFactory(),
            async_client_factory=factory,
        )
        assert await pool.execute_sharded([1], _return_async_item) == [1]

        if first_close == "cancel":
            first_attempt = asyncio.create_task(pool.aclose())
            await close_started.wait()
            first_attempt.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first_attempt
        else:
            with pytest.raises(RuntimeError, match="could not be closed"):
                await pool.aclose()

        assert clients[0].close_calls == 1
        await pool.aclose()
        assert clients[0].close_calls == 2
        with pytest.raises(RuntimeError, match="closed"):
            await pool.execute_sharded([2], _return_async_item)

    asyncio.run(exercise())


def test_repeated_failures_do_not_retain_closed_historical_clients() -> None:
    target = load_targets("normal")[0]
    factory = FakeSyncFactory()
    pool = TdxNodePool(
        [target],
        timeout_seconds=1.0,
        failure_threshold=100,
        client_factory=factory,
        async_client_factory=FakeAsyncFactory(),
    )
    references: list[weakref.ReferenceType[FakeSyncClient]] = []

    def fail_once() -> weakref.ReferenceType[FakeSyncClient]:
        with pytest.raises(TdxNodePoolError):
            pool.execute(
                lambda _client: (_ for _ in ()).throw(FakeTransportError("disconnected"))
            )
        client = factory.clients.pop()
        return weakref.ref(client)

    for _ in range(20):
        references.append(fail_once())
    gc.collect()

    assert all(reference() is None for reference in references)
    pool.close()


def test_business_exception_propagates_without_failover_or_health_penalty() -> None:
    targets = load_targets("normal")[:2]
    attempts: list[str] = []
    error = ValueError("invalid quote payload")
    pool = TdxNodePool(
        targets,
        timeout_seconds=1.0,
        failure_threshold=1,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
    )

    def operation(client: FakeSyncClient) -> None:
        attempts.append(client.address)
        raise error

    with pytest.raises(ValueError) as raised:
        pool.execute(operation)

    assert raised.value is error
    assert attempts == [targets[0].address]
    assert [node["consecutive_failures"] for node in pool.health_snapshot()["nodes"]] == [0, 0]
    pool.close()


def test_async_per_item_failover_tries_each_node_once_and_chains_last_transport_error() -> None:
    async def exercise() -> None:
        targets = load_targets("normal")
        attempts: list[str] = []
        errors: list[FakeTransportError] = []
        pool = TdxNodePool(
            targets,
            timeout_seconds=1.0,
            failure_threshold=10,
            client_factory=FakeSyncFactory(),
            async_client_factory=FakeAsyncFactory(),
        )

        async def operation(client: FakeAsyncClient, _item: int) -> int:
            attempts.append(client.address)
            error = FakeTransportError(f"{client.address} unavailable")
            errors.append(error)
            raise error

        with pytest.raises(TdxNodePoolError) as raised:
            await pool.execute_sharded([1], operation)

        assert attempts == [target.address for target in targets]
        assert len(attempts) == len(set(attempts))
        assert raised.value.__cause__ is errors[-1]
        await pool.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize("invalid", [True, False, 1.0, 1.5, 0, -1])
def test_failure_threshold_rejects_bool_float_and_nonpositive_values(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        TdxNodePool(
            load_targets("normal")[:1],
            timeout_seconds=1.0,
            failure_threshold=invalid,  # type: ignore[arg-type]
            client_factory=FakeSyncFactory(),
            async_client_factory=FakeAsyncFactory(),
        )


@pytest.mark.parametrize("invalid", [True, False, 1.0, 1.5, 0, -1])
def test_max_concurrency_rejects_bool_float_and_nonpositive_values(invalid: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        TdxNodePool(
            load_targets("normal")[:1],
            timeout_seconds=1.0,
            max_concurrency=invalid,  # type: ignore[arg-type]
            client_factory=FakeSyncFactory(),
            async_client_factory=FakeAsyncFactory(),
        )


async def _return_async_item(_client: FakeAsyncClient, item: int) -> int:
    return item
