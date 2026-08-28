from __future__ import annotations

import json
from pathlib import Path

from workbench.providers.tdx.transaction_fetcher import TransactionFetcher, shard_symbols


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


class _FakeNormalClient:
    def __init__(self, pages: list[list[object]]) -> None:
        self._pages = pages
        self.calls: list[tuple[object, str, int, int]] = []

    def get_transaction_data(
        self,
        market: object,
        code: str,
        start: int,
        count: int = 800,
    ) -> list[object]:
        self.calls.append((market, code, start, count))
        index = len(self.calls) - 1
        if index >= len(self._pages):
            return []
        return self._pages[index]


def test_shard_symbols_distributes_round_robin() -> None:
    shards = shard_symbols(["SH600000", "SZ000001", "BJ920001"], 2)
    assert shards[0] == ["SH600000", "BJ920001"]
    assert shards[1] == ["SZ000001"]


def test_transaction_fetcher_paginates_until_short_page() -> None:
    rows = json.loads((FIXTURE_DIR / "transactions.json").read_text(encoding="utf-8"))
    client = _FakeNormalClient([rows[:2], rows[2:]])
    fetcher = TransactionFetcher(client, page_size=2, max_pages=5)

    result = fetcher.fetch_symbol("SH600000")

    assert result.symbol == "SH600000"
    assert result.pages_fetched == 2
    assert result.exhausted is True
    assert len(result.rows) == 4


def test_transaction_fetcher_batch_collects_per_symbol() -> None:
    rows = json.loads((FIXTURE_DIR / "transactions.json").read_text(encoding="utf-8"))
    client = _FakeNormalClient([rows, rows])
    fetcher = TransactionFetcher(client, page_size=800, max_pages=1)

    payload = fetcher.fetch_batch(["SH600000", "SZ000001"], shard_count=2)

    assert set(payload) == {"SH600000", "SZ000001"}
    assert len(client.calls) == 2
