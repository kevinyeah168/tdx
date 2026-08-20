from __future__ import annotations

from typing import Callable, Protocol, TypeAlias

from easy_tdx import AsyncTdxClient, MacClient, TdxClient


class SyncTdxClient(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...


class AsyncTdxClientProtocol(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...


SyncClientFactory: TypeAlias = Callable[[str, int, float], SyncTdxClient]
AsyncClientFactory: TypeAlias = Callable[[str, int, float], AsyncTdxClientProtocol]


def create_tdx_client(address: str, port: int, timeout: float) -> TdxClient:
    return TdxClient(
        host=address,
        port=port,
        timeout=timeout,
        auto_reconnect=False,
    )


def create_async_tdx_client(address: str, port: int, timeout: float) -> AsyncTdxClient:
    return AsyncTdxClient(
        host=address,
        port=port,
        timeout=timeout,
        auto_reconnect=False,
    )


def create_mac_client(address: str, port: int, timeout: float) -> MacClient:
    return MacClient(
        host=address,
        port=port,
        timeout=timeout,
        auto_reconnect=False,
    )
