from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from workbench.config import WorkbenchSettings
from workbench.domain import BarPeriod
from workbench.providers.tdx.bars import (
    BAR_PERIOD_TO_KLINE,
    BAR_PERIOD_TO_MAC,
    TdxBarService,
    local_lday_path,
    pack_lday_record,
    parse_lday_record,
    read_local_daily_bars,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


def test_parse_lday_record_decodes_prices() -> None:
    payload = pack_lday_record(
        date_int=20260820,
        open_price=12.1,
        high=12.5,
        low=12.0,
        close=12.34,
        amount=12340.0,
        volume=1000,
    )
    record = parse_lday_record(payload)
    assert record["close"] == pytest.approx(12.34)
    assert record["volume"] == 1000


def test_read_local_daily_bars_returns_ascending_day_bars(tmp_path: Path) -> None:
    tdx_home = tmp_path / "tdx"
    path = local_lday_path(tdx_home, "SH600000")
    path.parent.mkdir(parents=True)
    path.write_bytes(
        pack_lday_record(
            date_int=20260819,
            open_price=12.0,
            high=12.2,
            low=11.9,
            close=12.1,
            amount=1000.0,
            volume=100,
        )
        + pack_lday_record(
            date_int=20260820,
            open_price=12.1,
            high=12.5,
            low=12.0,
            close=12.34,
            amount=1234.0,
            volume=120,
        )
    )

    bars = read_local_daily_bars(tdx_home, "SH600000", count=2)

    assert len(bars) == 2
    assert bars[0].timestamp == datetime(2026, 8, 19)
    assert bars[1].close == pytest.approx(12.34)


def test_period_mapping_covers_all_supported_periods() -> None:
    periods: tuple[BarPeriod, ...] = ("day", "week", "month", "1m", "5m", "15m", "30m", "60m")
    assert set(BAR_PERIOD_TO_KLINE) == set(periods)
    assert set(BAR_PERIOD_TO_MAC) == set(periods)


def test_fixture_bar_service_returns_sorted_rows() -> None:
    rows = json.loads((FIXTURE_DIR / "bars.json").read_text(encoding="utf-8"))
    service = TdxBarService(
        WorkbenchSettings(),
        fixture_rows={"SH600000": rows},
    )

    bars = service.fetch_bars("SH600000", "day", 2)

    assert len(bars) == 2
    assert bars[0].timestamp < bars[1].timestamp
    assert bars[-1].close == pytest.approx(12.7)


class _FakeEnhancedClient:
    def get_stock_kline(
        self,
        market: int,
        code: str,
        period: object,
        start: int,
        count: int,
    ) -> list[dict[str, object]]:
        del market, code, period, start, count
        return [
            {
                "datetime": "2026-08-20 09:31",
                "open": 12.5,
                "high": 12.6,
                "low": 12.4,
                "close": 12.55,
                "vol": 1000,
                "amount": 12550.0,
            }
        ]


def test_remote_bar_service_uses_enhanced_client() -> None:
    service = TdxBarService(WorkbenchSettings(), enhanced_client=_FakeEnhancedClient())

    bars = service.fetch_bars("SH600000", "5m", 1)

    assert len(bars) == 1
    assert bars[0].period == "5m"
    assert bars[0].close == pytest.approx(12.55)
