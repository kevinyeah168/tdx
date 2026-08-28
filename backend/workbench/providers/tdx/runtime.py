from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from easy_tdx.config import get_port
from easy_tdx.transport.sync import KNOWN_HOSTS, MAC_HOSTS

from workbench.config import WorkbenchSettings
from workbench.providers.tdx.bars import TdxBarService
from workbench.providers.tdx.catalog import TdxCatalogLoader
from workbench.providers.tdx.node_pool import MacNodePool, NodeTarget, TdxNodePool
from workbench.providers.tdx.provider import TdxMarketProvider
from workbench.providers.tdx.quotes import TdxQuoteService

ResultT = TypeVar("ResultT")


@dataclass(slots=True)
class PoolBackedNormalClient:
    pool: TdxNodePool

    def get_security_list_all(self, pages: int | str = "all") -> object:
        return self.pool.execute(lambda client: client.get_security_list_all(pages=pages))

    def get_security_quotes(self, stocks: list[tuple[object, str]]) -> object:
        return self.pool.execute(lambda client: client.get_security_quotes(stocks))

    def get_transaction_data(
        self,
        market: object,
        code: str,
        start: int,
        count: int = 800,
    ) -> object:
        return self.pool.execute(
            lambda client: client.get_transaction_data(market, code, start, count)
        )

    def get_security_bars(
        self,
        market: object,
        code: str,
        category: object,
        start: int,
        count: int = 800,
    ) -> object:
        return self.pool.execute(
            lambda client: client.get_security_bars(market, code, category, start, count)
        )


@dataclass(slots=True)
class PoolBackedEnhancedClient:
    pool: MacNodePool

    def get_board_list(self, *, board_type: object, count: int) -> object:
        return self.pool.execute(
            lambda client: client.get_board_list(board_type=board_type, count=count)
        )

    def get_board_members(self, board_symbol: str, *, count: int) -> object:
        return self.pool.execute(
            lambda client: client.get_board_members(board_symbol, count=count)
        )

    def get_board_summary(self, board_symbol: str) -> object:
        return self.pool.execute(lambda client: client.get_board_summary(board_symbol))

    def get_stock_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: object = None,
    ) -> object:
        return self.pool.execute(
            lambda client: client.get_stock_quotes(stocks, fields=fields)
        )

    def get_stock_kline(
        self,
        market: int,
        code: str,
        period: object,
        start: int,
        count: int,
    ) -> object:
        return self.pool.execute(
            lambda client: client.get_stock_kline(market, code, period, start, count)
        )


def build_node_targets(hosts: tuple[str, ...], *, limit: int, port: int) -> tuple[NodeTarget, ...]:
    return tuple(NodeTarget(address=host, port=port) for host in hosts[:limit])


def create_real_provider(settings: WorkbenchSettings) -> TdxMarketProvider:
    port = get_port()
    limit = settings.node_pool_size
    normal_pool = TdxNodePool(
        build_node_targets(tuple(KNOWN_HOSTS), limit=limit, port=port),
        timeout_seconds=settings.normal_node_timeout_seconds,
        failure_threshold=max(settings.node_retry_count, 1),
        max_concurrency=limit,
    )
    enhanced_pool = MacNodePool(
        build_node_targets(tuple(MAC_HOSTS), limit=limit, port=port),
        timeout_seconds=settings.enhanced_node_timeout_seconds,
        failure_threshold=max(settings.node_retry_count, 1),
    )
    normal_client = PoolBackedNormalClient(normal_pool)
    enhanced_client = PoolBackedEnhancedClient(enhanced_pool)
    catalog_loader = TdxCatalogLoader(
        normal_client=normal_client,
        enhanced_client=enhanced_client,
        tdx_home=settings.tdx_home,
        source="tdx.network",
        settings=settings,
    )
    quote_service = TdxQuoteService(
        settings=settings,
        enhanced_client=enhanced_client,
        normal_client=normal_client,
    )
    bar_service = TdxBarService(
        settings,
        tdx_home=settings.tdx_home,
        enhanced_client=enhanced_client,
        normal_client=normal_client,
    )
    return TdxMarketProvider(
        settings,
        catalog_loader=catalog_loader,
        quote_service=quote_service,
        bar_service=bar_service,
        normal_client=normal_client,
        normal_pool=normal_pool,
        enhanced_pool=enhanced_pool,
        enhanced_client=enhanced_client,
    )
