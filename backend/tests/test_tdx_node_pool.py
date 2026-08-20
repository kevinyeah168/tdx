from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

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
    assert state["circuit_open_until"] == 130.0


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
    assert state["circuit_open_until"] is None
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
    assert node_snapshot(enhanced_pool, shared_target.address)["circuit_open_until"] is None


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
    pool = TdxNodePool(
        targets,
        timeout_seconds=1.0,
        failure_threshold=1,
        cooldown_seconds=45.0,
        clock=clock,
        client_factory=FakeSyncFactory(),
        async_client_factory=FakeAsyncFactory(),
    )

    def leak_prone_failure(client: FakeSyncClient) -> None:
        attempts.append(client.address)
        raise RuntimeError(r"password=hunter2 token=abcd C:\Users\alice\private\nodes.json")

    with pytest.raises(TdxNodePoolError) as raised:
        pool.execute(leak_prone_failure)

    assert str(raised.value) == "all normal TDX nodes are unavailable"
    assert attempts == [target.address for target in targets]
    assert raised.value.diagnostics == pool.health_snapshot()["nodes"]

    serialized = json.dumps(pool.health_snapshot(), sort_keys=True)
    assert "hunter2" not in serialized
    assert "abcd" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized
    assert "C:" not in serialized
    assert "Users" not in serialized


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
        "circuit_open_until",
        "last_error",
    }
    assert snapshot["nodes"][0] == {
        "address": target.address,
        "port": target.port,
        "latency_ms": 12.5,
        "consecutive_failures": 1,
        "circuit_open_until": 115.0,
        "last_error": "OSError",
    }
    assert "credentials" not in snapshot
    assert "traceback" not in snapshot
