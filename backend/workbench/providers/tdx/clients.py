from __future__ import annotations

from typing import Callable, Protocol, TypeAlias

from easy_tdx import AsyncTdxClient, KlineCategory, MacClient, Market, TdxClient


NETWORK_FULL_LIST_PAGE_LIMIT = 1_000_000


class SyncTdxClient(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...


class AsyncTdxClientProtocol(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...


class NormalProbeClient(SyncTdxClient, Protocol):
    def get_security_list_all(self, pages: int | str = "all") -> object: ...

    def get_security_quotes(self, stocks: list[tuple[Market, str]]) -> object: ...

    def get_transaction_data(
        self,
        market: Market,
        code: str,
        start: int,
        count: int = 800,
    ) -> object: ...

    def get_minute_time_data(self, market: Market, code: str) -> object: ...

    def get_security_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
    ) -> object: ...


class EnhancedProbeClient(SyncTdxClient, Protocol):
    def get_board_list(self, *, board_type: object, count: int) -> object: ...

    def get_board_members(self, board_symbol: str, *, count: int) -> object: ...

    def get_capital_flow(self, market: int, code: str) -> object: ...

    def get_stock_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: object = None,
    ) -> object: ...

    def get_stock_kline(
        self,
        market: int,
        code: str,
        period: object,
        start: int,
        count: int,
    ) -> object: ...


def get_security_list_all_network(client: NormalProbeClient) -> object:
    """Fetch every installed easy-tdx page while bypassing its ``pages='all'`` cache."""

    return client.get_security_list_all(pages=NETWORK_FULL_LIST_PAGE_LIMIT)


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
