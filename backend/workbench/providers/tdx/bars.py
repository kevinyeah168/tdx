from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from easy_tdx.mac.enums import Period
from easy_tdx.models.enums import KlineCategory, Market

from workbench.config import WorkbenchSettings
from workbench.domain import Bar, BarPeriod
from workbench.providers.tdx.symbols import market_from_label, parse_symbol


LDAY_RECORD_SIZE = 32
LDAY_STRUCT = struct.Struct("<IIIIIfII")

BAR_PERIOD_TO_KLINE: dict[BarPeriod, KlineCategory] = {
    "day": KlineCategory.DAY,
    "week": KlineCategory.WEEK,
    "month": KlineCategory.MONTH,
    "1m": KlineCategory.MIN_1,
    "5m": KlineCategory.MIN_5,
    "15m": KlineCategory.MIN_15,
    "30m": KlineCategory.MIN_30,
    "60m": KlineCategory.MIN_60,
}

BAR_PERIOD_TO_MAC: dict[BarPeriod, Period] = {
    "day": Period.DAILY,
    "week": Period.WEEKLY,
    "month": Period.MONTHLY,
    "1m": Period.MIN_1,
    "5m": Period.MIN_5,
    "15m": Period.MIN_15,
    "30m": Period.MIN_30,
    "60m": Period.MIN_60,
}


class EnhancedBarClient(Protocol):
    def get_stock_kline(
        self,
        market: int,
        code: str,
        period: object,
        start: int,
        count: int,
    ) -> object: ...


class NormalBarClient(Protocol):
    def get_security_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
    ) -> object: ...


def local_lday_path(tdx_home: Path, symbol: str) -> Path:
    market_label, code = parse_symbol(symbol)
    return tdx_home / "vipdoc" / market_label.lower() / "lday" / f"{market_label.lower()}{code}.day"


def parse_lday_record(data: bytes) -> dict[str, float | int]:
    if len(data) != LDAY_RECORD_SIZE:
        raise ValueError("lday record must be 32 bytes")
    date_int, open_raw, high_raw, low_raw, close_raw, amount, volume, _reserved = LDAY_STRUCT.unpack(data)
    if date_int <= 0:
        raise ValueError("lday record has invalid date")
    return {
        "date": int(date_int),
        "open": open_raw / 100.0,
        "high": high_raw / 100.0,
        "low": low_raw / 100.0,
        "close": close_raw / 100.0,
        "amount": float(amount),
        "volume": float(volume),
    }


def pack_lday_record(
    *,
    date_int: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    amount: float,
    volume: int,
) -> bytes:
    return LDAY_STRUCT.pack(
        int(date_int),
        int(round(open_price * 100)),
        int(round(high * 100)),
        int(round(low * 100)),
        int(round(close * 100)),
        float(amount),
        int(volume),
        0,
    )


def _timestamp_from_value(value: object, *, period: BarPeriod) -> datetime:
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        if isinstance(converted, datetime):
            return converted
    text = str(value).strip()
    if not text:
        raise ValueError("bar row is missing datetime")
    if period == "day":
        if len(text) >= 10:
            return datetime.strptime(text[:10], "%Y-%m-%d")
        return datetime.strptime(text[:8], "%Y%m%d")
    if " " in text:
        return datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", ""))
    if len(text) == 8:
        return datetime.strptime(text, "%Y%m%d")
    return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")


def _row_value(row: object, *keys: str, default: float = 0.0) -> float:
    if isinstance(row, dict):
        for key in keys:
            if key in row and row[key] is not None:
                return float(row[key])
        return default
    for key in keys:
        if hasattr(row, key):
            value = getattr(row, key)
            if value is not None:
                return float(value)
    return default


def normalize_bar_row(row: object, *, symbol: str, period: BarPeriod) -> Bar:
    if isinstance(row, dict) and "date" in row and "datetime" not in row:
        date_int = int(row["date"])
        timestamp = datetime.strptime(str(date_int), "%Y%m%d")
    else:
        timestamp = _timestamp_from_value(
            row.get("datetime") if isinstance(row, dict) else getattr(row, "datetime", None),
            period=period,
        )
    return Bar(
        symbol=symbol,
        period=period,
        timestamp=timestamp,
        open=_row_value(row, "open"),
        high=_row_value(row, "high"),
        low=_row_value(row, "low"),
        close=_row_value(row, "close"),
        volume=_row_value(row, "vol", "volume"),
        amount=_row_value(row, "amount"),
    )


def read_local_daily_bars(
    tdx_home: Path,
    symbol: str,
    *,
    count: int,
) -> list[Bar]:
    if count < 1:
        raise ValueError("count must be at least 1")
    path = local_lday_path(tdx_home, symbol)
    if not path.is_file():
        return []
    raw = path.read_bytes()
    if len(raw) % LDAY_RECORD_SIZE != 0:
        raise ValueError(f"invalid lday file size: {path}")
    bars: list[Bar] = []
    for offset in range(0, len(raw), LDAY_RECORD_SIZE):
        record = parse_lday_record(raw[offset : offset + LDAY_RECORD_SIZE])
        bars.append(
            normalize_bar_row(
                {
                    "date": record["date"],
                    "open": record["open"],
                    "high": record["high"],
                    "low": record["low"],
                    "close": record["close"],
                    "volume": record["volume"],
                    "amount": record["amount"],
                },
                symbol=symbol,
                period="day",
            )
        )
    bars.sort(key=lambda bar: bar.timestamp)
    return bars[-count:]


def _iter_remote_rows(response: object) -> list[object]:
    if response is None:
        return []
    if hasattr(response, "to_dict"):
        payload = response.to_dict(orient="records")
        if isinstance(payload, list):
            return payload
    if isinstance(response, list):
        return response
    if hasattr(response, "__iter__") and not isinstance(response, (str, bytes, dict)):
        return list(response)
    return []


def fetch_remote_bars(
    *,
    symbol: str,
    period: BarPeriod,
    count: int,
    enhanced_client: EnhancedBarClient | None,
    normal_client: NormalBarClient | None,
) -> list[Bar]:
    if count < 1:
        raise ValueError("count must be at least 1")
    market_label, code = parse_symbol(symbol)
    market = market_from_label(market_label)
    rows: list[object] = []
    if enhanced_client is not None:
        rows = _iter_remote_rows(
            enhanced_client.get_stock_kline(
                int(market),
                code,
                BAR_PERIOD_TO_MAC[period],
                0,
                count,
            )
        )
    elif normal_client is not None:
        rows = _iter_remote_rows(
            normal_client.get_security_bars(
                market,
                code,
                BAR_PERIOD_TO_KLINE[period],
                0,
                count,
            )
        )
    bars = [normalize_bar_row(row, symbol=symbol, period=period) for row in rows]
    bars.sort(key=lambda bar: bar.timestamp)
    return bars[-count:]


class TdxBarService:
    def __init__(
        self,
        settings: WorkbenchSettings,
        *,
        tdx_home: Path | None = None,
        fixture_rows: dict[str, list[object]] | None = None,
        enhanced_client: EnhancedBarClient | None = None,
        normal_client: NormalBarClient | None = None,
    ) -> None:
        self._settings = settings
        self._tdx_home = tdx_home or settings.tdx_home
        self._fixture_rows = fixture_rows or {}
        self._enhanced_client = enhanced_client
        self._normal_client = normal_client

    def fetch_bars(self, symbol: str, period: BarPeriod, count: int) -> list[Bar]:
        normalized = symbol.upper()
        if normalized in self._fixture_rows:
            bars = [
                normalize_bar_row(row, symbol=normalized, period=period)
                for row in self._fixture_rows[normalized]
            ]
            bars.sort(key=lambda bar: bar.timestamp)
            return bars[-count:]
        bars: list[Bar] = []
        if period == "day" and self._tdx_home is not None:
            bars = read_local_daily_bars(self._tdx_home, normalized, count=count)
        if len(bars) >= count:
            return bars[-count:]
        remote = fetch_remote_bars(
            symbol=normalized,
            period=period,
            count=count,
            enhanced_client=self._enhanced_client,
            normal_client=self._normal_client,
        )
        if remote:
            return remote
        return bars
