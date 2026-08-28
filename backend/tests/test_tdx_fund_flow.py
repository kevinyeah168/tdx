from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from workbench.domain import DataQuality
from workbench.providers.tdx.fund_flow import build_stock_minutes


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


def test_build_stock_minutes_uses_official_main_and_gap_other_tiers() -> None:
    rows = json.loads((FIXTURE_DIR / "quotes.json").read_text(encoding="utf-8"))
    first = build_stock_minutes(
        trade_date=date(2026, 8, 20),
        minute="09:30",
        quote_rows=rows,
        previous_main_cum={},
        previous_amount_cum={},
        observed_at=datetime(2026, 8, 20, 9, 30),
    )
    second = build_stock_minutes(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        quote_rows=rows,
        previous_main_cum={stock.symbol: stock.funds.main.cumulative for stock in first},
        previous_amount_cum={stock.symbol: stock.amount_delta for stock in first},
        observed_at=datetime(2026, 8, 20, 9, 31),
    )

    sh600000_first = next(stock for stock in first if stock.symbol == "SH600000")
    sh600000_second = next(stock for stock in second if stock.symbol == "SH600000")

    assert sh600000_first.funds.main.quality is DataQuality.OFFICIAL
    assert sh600000_first.funds.main.cumulative == 2_500_000
    assert sh600000_second.funds.main.delta == 0.0
    assert sh600000_first.funds.super.quality is DataQuality.GAP
