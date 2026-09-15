from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from workbench.providers.eastmoney.gray_market import GrayMarketProvider


def _row(code: str, dark: float = 1.0) -> dict:
    return {
        "3": "0",
        "4": code,
        "5": "20260911103000",
        "6": dark,
        "7": 2.0,
        "8": dark + 2.0,
        "16": f"stock-{code}",
    }


def test_fetch_full_market_gray_snapshots_paginates_until_short_page() -> None:
    provider = GrayMarketProvider()
    pages = {
        1: [_row("600000"), _row("600001")],
        2: [_row("600002")],
    }

    def fake_payload(*, start_page: int, num_per_page: int, **kwargs):
        rows = pages.get(start_page, [])
        return {"data": rows}

    with patch.object(provider, "_fetch_darktrade_payload", side_effect=fake_payload):
        samples = provider.fetch_full_market_gray_snapshots(
            trade_date="2026-09-11",
            sampled_at=datetime(2026, 9, 11, 10, 30),
            page_size=2,
        )

    assert len(samples) == 3
    assert {sample.code for sample in samples} == {"600000", "600001", "600002"}


def test_fetch_full_market_gray_snapshots_rejects_oversized_page() -> None:
    provider = GrayMarketProvider()
    with pytest.raises(ValueError, match="page_size"):
        provider.fetch_full_market_gray_snapshots(trade_date="2026-09-11", page_size=200)
