from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from workbench.config import WorkbenchSettings
from workbench.domain import DataQuality
from workbench.providers.tdx.quotes import TdxQuoteService, normalize_quote_batch


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


def test_normalize_quote_batch_handles_zero_previous_close_and_change_pct() -> None:
    rows = [{"symbol": "SH600000", "market": "SH", "code": "600000", "price": 0, "pre_close": 0}]
    snapshots = normalize_quote_batch(
        rows,
        trade_date=date(2026, 8, 20),
        minute="09:31",
        observed_at=datetime(2026, 8, 20, 9, 31),
        source="fixture",
        quality=DataQuality.OFFICIAL,
    )

    assert snapshots[0].change_pct == 0.0


def test_quote_service_batches_fixture_rows() -> None:
    rows = json.loads((FIXTURE_DIR / "quotes.json").read_text(encoding="utf-8"))
    service = TdxQuoteService(settings=WorkbenchSettings(), fixture_rows=rows)
    envelope = service.quotes(
        ["SH600000", "SZ000001"],
        trade_date=date(2026, 8, 20),
        minute="09:31",
        observed_at=datetime(2026, 8, 20, 9, 31),
    )

    assert envelope.data is not None
    assert {snapshot.symbol for snapshot in envelope.data} == {"SH600000", "SZ000001"}
    assert envelope.quality is DataQuality.OFFICIAL
