from __future__ import annotations

from datetime import date, datetime

from workbench.domain import DataQuality
from workbench.providers.tdx.market_scope_records import (
    MARKET_SCOPE_SECTOR_CODES,
    build_market_scope_minutes_from_yuntu,
    is_shenzhen_main_stock_code,
)
from workbench.providers.tdx.yuntu_sector_flow import YuntuStockQuote


def test_is_shenzhen_main_stock_code() -> None:
    assert is_shenzhen_main_stock_code("000001")
    assert is_shenzhen_main_stock_code("002594")
    assert not is_shenzhen_main_stock_code("300001")
    assert not is_shenzhen_main_stock_code("600519")
    assert not is_shenzhen_main_stock_code("880001")


def test_build_market_scope_minutes_from_yuntu() -> None:
    rows = [
        YuntuStockQuote(
            stockcode=MARKET_SCOPE_SECTOR_CODES["hs"],
            setcode=1,
            dqzf=0.008,
            f_amo_sum_wan=1000.0,
            now=0.0,
            z_close=0.0,
        ),
        YuntuStockQuote(
            stockcode=MARKET_SCOPE_SECTOR_CODES["sh"],
            setcode=1,
            dqzf=0.005,
            f_amo_sum_wan=400.0,
            now=0.0,
            z_close=0.0,
        ),
        YuntuStockQuote(
            stockcode=MARKET_SCOPE_SECTOR_CODES["kc"],
            setcode=1,
            dqzf=0.02,
            f_amo_sum_wan=300.0,
            now=0.0,
            z_close=0.0,
        ),
        YuntuStockQuote(
            stockcode=MARKET_SCOPE_SECTOR_CODES["cy"],
            setcode=1,
            dqzf=0.015,
            f_amo_sum_wan=150.0,
            now=0.0,
            z_close=0.0,
        ),
        YuntuStockQuote(
            stockcode="000001",
            setcode=0,
            dqzf=0.01,
            f_amo_sum_wan=20.0,
            now=11.0,
            z_close=10.0,
        ),
        YuntuStockQuote(
            stockcode="300001",
            setcode=0,
            dqzf=0.03,
            f_amo_sum_wan=50.0,
            now=12.0,
            z_close=11.0,
        ),
    ]
    records = build_market_scope_minutes_from_yuntu(
        trade_date=date(2026, 9, 18),
        minute="09:31",
        rows=rows,
        previous_main_cum={},
        observed_at=datetime(2026, 9, 18, 9, 31),
        batch_id="2026-09-18T09:31-yuntu",
    )
    by_scope = {record.scope: record for record in records}
    assert set(by_scope) == {"hs", "sh", "kc", "sz", "cy"}
    assert by_scope["hs"].funds.main.cumulative == 10_000_000.0
    assert by_scope["sz"].funds.main.cumulative == 200_000.0
    assert by_scope["sz"].funds.main.quality is DataQuality.AGGREGATED
    assert by_scope["hs"].change_pct == 0.8
