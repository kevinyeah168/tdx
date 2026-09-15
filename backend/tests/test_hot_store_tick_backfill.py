from datetime import date

from pathlib import Path

from workbench.storage.hot_store import HotStore, TICK_BACKFILL_BATCH_MARKER
from tests.test_hot_store import sector_record, stock_record


def test_count_tick_backfill_minutes_filters_batch_id(tmp_path: Path) -> None:
    hot = HotStore(tmp_path / "hot.sqlite")
    hot.initialize()
    trade_date = date(2026, 9, 2)
    trade_date_str = trade_date.isoformat()
    priority = sector_record(sector_id="880548", batch_id=f"{trade_date_str}T09:31").model_copy(
        update={"trade_date": trade_date}
    )
    tick = sector_record(sector_id="880548", batch_id=f"{trade_date_str}T{TICK_BACKFILL_BATCH_MARKER}")
    tick = tick.model_copy(update={"trade_date": trade_date, "minute": "09:32"})
    hot.write_sectors([priority, tick])

    assert hot.count_sector_minutes(trade_date_str, "880548") == 2
    assert hot.count_sector_tick_backfill_minutes(trade_date_str, "880548") == 1

    stock_priority = stock_record(10.0, symbol="SH600000", batch_id=f"{trade_date_str}T09:31").model_copy(
        update={"trade_date": trade_date}
    )
    stock_tick = stock_record(
        10.5, symbol="SH600000", batch_id=f"{trade_date_str}T{TICK_BACKFILL_BATCH_MARKER}"
    )
    # Meaningful tick curves must exceed the flat-tick epsilon used by the hot store.
    stock_tick = stock_tick.model_copy(
        update={
            "trade_date": trade_date,
            "minute": "09:32",
            "funds": stock_tick.funds.model_copy(
                update={
                    "main": stock_tick.funds.main.model_copy(update={"cumulative": 2.5e8, "delta": 2.5e8})
                }
            ),
        }
    )
    hot.write_stocks([stock_priority, stock_tick])

    assert hot.count_stock_minutes(trade_date_str, "SH600000") == 2
    assert hot.count_stock_tick_backfill_minutes(trade_date_str, "SH600000") == 1
