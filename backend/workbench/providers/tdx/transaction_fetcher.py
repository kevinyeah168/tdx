from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from easy_tdx import Market

from workbench.providers.tdx.symbols import market_from_label, parse_symbol
from workbench.providers.tdx.transactions import dedupe_transactions


DEFAULT_PAGE_SIZE = 800
DEFAULT_MAX_PAGES = 10


class NormalTransactionClient(Protocol):
    def get_transaction_data(
        self,
        market: Market,
        code: str,
        start: int,
        count: int = 800,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class TransactionFetchResult:
    symbol: str
    rows: list[object]
    pages_fetched: int
    exhausted: bool


def shard_symbols(symbols: Iterable[str], shard_count: int) -> dict[int, list[str]]:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    buckets: dict[int, list[str]] = {index: [] for index in range(shard_count)}
    for index, symbol in enumerate(symbols):
        buckets[index % shard_count].append(symbol.upper())
    return buckets


class TransactionFetcher:
    def __init__(
        self,
        normal_client: NormalTransactionClient,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self._client = normal_client
        self._page_size = page_size
        self._max_pages = max_pages

    def fetch_symbol(self, symbol: str) -> TransactionFetchResult:
        market_label, code = parse_symbol(symbol)
        market = market_from_label(market_label)
        rows: list[object] = []
        start = 0
        pages = 0
        exhausted = False
        while pages < self._max_pages:
            page = self._client.get_transaction_data(market, code, start, self._page_size)
            page_rows = list(page) if isinstance(page, list) else []
            if not page_rows:
                exhausted = True
                break
            rows.extend(page_rows)
            pages += 1
            if len(page_rows) < self._page_size:
                exhausted = True
                break
            start += len(page_rows)
        return TransactionFetchResult(
            symbol=symbol.upper(),
            rows=dedupe_transactions(rows),
            pages_fetched=pages,
            exhausted=exhausted,
        )

    def fetch_batch(
        self,
        symbols: Iterable[str],
        *,
        shard_count: int = 1,
        on_symbol: Callable[[TransactionFetchResult], None] | None = None,
    ) -> dict[str, list[object]]:
        shards = shard_symbols(symbols, shard_count)
        results: dict[str, list[object]] = {}
        for bucket in shards.values():
            for symbol in bucket:
                fetched = self.fetch_symbol(symbol)
                results[fetched.symbol] = fetched.rows
                if on_symbol is not None:
                    on_symbol(fetched)
        return results
