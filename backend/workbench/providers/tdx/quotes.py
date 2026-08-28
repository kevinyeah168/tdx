from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from easy_tdx import Market

from workbench.config import WorkbenchSettings
from workbench.domain import DataEnvelope, DataQuality, QuoteSnapshot
from workbench.providers.tdx.symbols import market_label, normalize_code, parse_symbol, to_symbol


_MARKET_INT_TO_LABEL = {
    int(Market.SZ): "SZ",
    int(Market.SH): "SH",
    int(Market.BJ): "BJ",
}


def _rows_from_response(response: object) -> list[object]:
    if response is None:
        return []
    if hasattr(response, "to_dict"):
        records = response.to_dict(orient="records")
        if isinstance(records, list):
            return records
    if isinstance(response, list):
        return response
    if hasattr(response, "__iter__") and not isinstance(response, (str, bytes, dict)):
        return list(response)
    return []


class QuoteClient(Protocol):
    def get_stock_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: object = None,
    ) -> object: ...

    def get_security_quotes(self, stocks: list[tuple[object, str]]) -> object: ...


def _change_pct(price: float, previous_close: float) -> float:
    if previous_close <= 0:
        return 0.0
    return round((price - previous_close) / previous_close * 100.0, 4)


def _row_value(row: object, *names: str, default: object = 0) -> object:
    for name in names:
        if isinstance(row, dict) and name in row:
            return row[name]
        if hasattr(row, name):
            return getattr(row, name)
    return default


def _symbol_from_row(row: object) -> str:
    explicit = _row_value(row, "symbol", default="")
    if explicit:
        return str(explicit).upper()
    market_raw = _row_value(row, "market", default="SH")
    if isinstance(market_raw, Market):
        market = market_label(market_raw)
    elif isinstance(market_raw, int):
        market = _MARKET_INT_TO_LABEL.get(market_raw, "SH")
    else:
        market = market_label(str(market_raw))
    code = normalize_code(str(_row_value(row, "code", default="000000")))
    return to_symbol(market, code)


def normalize_quote_row(
    row: object,
    *,
    trade_date,
    minute: str,
    observed_at: datetime,
    source: str,
    quality: DataQuality,
) -> QuoteSnapshot:
    symbol = _symbol_from_row(row)
    parse_symbol(symbol)
    price = float(_row_value(row, "price", "close", "last", default=0))
    previous_close = float(_row_value(row, "pre_close", "last_close", "previous_close", default=0))
    volume = float(_row_value(row, "vol", "volume", default=0))
    amount = float(_row_value(row, "amount", "turnover", default=0))
    return QuoteSnapshot(
        symbol=symbol,
        trade_date=trade_date,
        minute=minute,
        price=price,
        previous_close=previous_close,
        change_pct=_change_pct(price, previous_close),
        volume=volume,
        amount=amount,
    )


def normalize_quote_batch(
    rows: list[object],
    *,
    trade_date,
    minute: str,
    observed_at: datetime,
    source: str,
    quality: DataQuality,
) -> list[QuoteSnapshot]:
    snapshots: list[QuoteSnapshot] = []
    seen: set[str] = set()
    for row in rows:
        snapshot = normalize_quote_row(
            row,
            trade_date=trade_date,
            minute=minute,
            observed_at=observed_at,
            source=source,
            quality=quality,
        )
        if snapshot.symbol in seen:
            continue
        seen.add(snapshot.symbol)
        snapshots.append(snapshot)
    return snapshots


class TdxQuoteService:
    def __init__(
        self,
        *,
        settings: WorkbenchSettings,
        enhanced_client: QuoteClient | None = None,
        normal_client: QuoteClient | None = None,
        fixture_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._enhanced_client = enhanced_client
        self._normal_client = normal_client
        self._fixture_rows = fixture_rows

    def quotes(self, symbols: list[str], *, trade_date, minute: str, observed_at: datetime) -> DataEnvelope[list[QuoteSnapshot]]:
        if self._fixture_rows is not None:
            requested = {symbol.upper() for symbol in symbols}
            rows = [row for row in self._fixture_rows if str(row["symbol"]).upper() in requested]
            data = normalize_quote_batch(
                rows,
                trade_date=trade_date,
                minute=minute,
                observed_at=observed_at,
                source="tdx.fixture.quotes",
                quality=DataQuality.OFFICIAL,
            )
            return DataEnvelope(
                data=data,
                source="tdx.fixture.quotes",
                quality=DataQuality.OFFICIAL,
                observed_at=observed_at,
                catalog_version="fixture",
            )

        if not symbols:
            return DataEnvelope(
                data=[],
                source="tdx.quotes",
                quality=DataQuality.OFFICIAL,
                observed_at=observed_at,
                catalog_version="live",
            )

        batch_size = self._settings.quote_batch_size
        snapshots: list[QuoteSnapshot] = []
        for start in range(0, len(symbols), batch_size):
            chunk = symbols[start : start + batch_size]
            rows = self._fetch_chunk(chunk)
            snapshots.extend(
                normalize_quote_batch(
                    rows,
                    trade_date=trade_date,
                    minute=minute,
                    observed_at=observed_at,
                    source="tdx.enhanced.quotes",
                    quality=DataQuality.OFFICIAL,
                )
            )
        return DataEnvelope(
            data=snapshots,
            source="tdx.enhanced.quotes",
            quality=DataQuality.OFFICIAL,
            observed_at=observed_at,
            catalog_version="live",
        )

    def _fetch_chunk(self, symbols: list[str]) -> list[object]:
        if self._enhanced_client is not None:
            stocks: list[tuple[int, str]] = []
            for symbol in symbols:
                market, code = parse_symbol(symbol)
                stocks.append(({"SH": 1, "SZ": 0, "BJ": 2}[market], code))
            try:
                from easy_tdx import QuoteField

                return _rows_from_response(
                    self._enhanced_client.get_stock_quotes(
                        stocks,
                        fields=[QuoteField.MAIN_NET_AMOUNT],
                    )
                )
            except Exception:
                return _rows_from_response(self._enhanced_client.get_stock_quotes(stocks))
        if self._normal_client is not None:
            from easy_tdx import Market

            stocks = [(Market[parse_symbol(symbol)[0]], parse_symbol(symbol)[1]) for symbol in symbols]
            return _rows_from_response(self._normal_client.get_security_quotes(stocks))
        raise ValueError("quote service requires a client or fixture rows")

    def fetch_quote_rows(self, symbols: list[str]) -> list[object]:
        if self._fixture_rows is not None:
            requested = {symbol.upper() for symbol in symbols}
            return [row for row in self._fixture_rows if str(row["symbol"]).upper() in requested]
        if not symbols:
            return []
        rows: list[object] = []
        batch_size = self._settings.quote_batch_size
        for start in range(0, len(symbols), batch_size):
            rows.extend(self._fetch_chunk(symbols[start : start + batch_size]))
        return rows
