from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.domain import DataQuality
from workbench.providers.tdx.fund_flow import apply_estimated_tiers, build_stock_minutes
from workbench.providers.tdx.transactions import (
    aggregate_tier_deltas,
    classify_tier,
    dedupe_transactions,
    signed_amount,
    transaction_amount,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


def test_transaction_amount_uses_lot_size() -> None:
    assert transaction_amount(10.0, 100) == 100_000.0


def test_signed_amount_respects_buy_and_sell() -> None:
    assert signed_amount(price=10.0, volume=100, side=0) == 100_000.0
    assert signed_amount(price=10.0, volume=100, side=1) == -100_000.0


def test_classify_tier_uses_default_thresholds() -> None:
    assert classify_tier(1_500_000) == "super"
    assert classify_tier(500_000) == "large"
    assert classify_tier(80_000) == "medium"
    assert classify_tier(10_000) == "small"


def test_dedupe_transactions_removes_exact_duplicates() -> None:
    rows = json.loads((FIXTURE_DIR / "transactions.json").read_text(encoding="utf-8"))
    assert len(dedupe_transactions(rows)) == 4


def test_aggregate_tier_deltas_sums_signed_flows() -> None:
    rows = json.loads((FIXTURE_DIR / "transactions.json").read_text(encoding="utf-8"))
    totals = aggregate_tier_deltas(dedupe_transactions(rows))
    assert totals.super_delta != 0.0 or totals.large_delta != 0.0


def test_apply_estimated_tiers_keeps_official_main() -> None:
    rows = json.loads((FIXTURE_DIR / "quotes.json").read_text(encoding="utf-8"))
    tx_rows = json.loads((FIXTURE_DIR / "transactions.json").read_text(encoding="utf-8"))
    stocks = build_stock_minutes(
        trade_date=__import__("datetime").date(2026, 8, 20),
        minute="09:31",
        quote_rows=rows[:1],
    )
    enriched = apply_estimated_tiers(
        stocks,
        {"SH600000": tx_rows},
    )
    assert enriched[0].funds.main.quality is DataQuality.OFFICIAL
    assert enriched[0].funds.super.quality is DataQuality.ESTIMATED
