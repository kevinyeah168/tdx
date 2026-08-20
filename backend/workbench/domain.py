from __future__ import annotations

from datetime import date, datetime
from enum import Enum
import re
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)


def validate_minute(value: str) -> str:
    if len(value) != 5 or value[2] != ":" or not value.replace(":", "").isdigit():
        raise ValueError("minute must use HH:MM format")
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as error:
        raise ValueError("minute must be a valid clock time") from error
    return value


def validate_nonblank_text(value: str) -> str:
    stripped_value = value.strip()
    if not stripped_value:
        raise ValueError("value must not be blank")
    return stripped_value


def validate_market_symbol(value: str) -> str:
    if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", value) is None:
        raise ValueError("symbol must use an SH, SZ, or BJ market prefix and six digits")
    return value


Minute = Annotated[str, AfterValidator(validate_minute)]
NonBlankText = Annotated[str, AfterValidator(validate_nonblank_text)]
MarketSymbol = Annotated[NonBlankText, AfterValidator(validate_market_symbol)]


class NormalizedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DataQuality(str, Enum):
    OFFICIAL = "official"
    AGGREGATED = "aggregated"
    ESTIMATED = "estimated"
    CALIBRATED = "calibrated"
    STALE = "stale"
    GAP = "gap"


PayloadT = TypeVar("PayloadT")


class DataEnvelope(NormalizedModel, Generic[PayloadT]):
    data: PayloadT | None = None
    source: NonBlankText
    quality: DataQuality
    observed_at: datetime
    catalog_version: NonBlankText
    gap_reason: NonBlankText | None = None

    @model_validator(mode="after")
    def validate_gap_semantics(self) -> "DataEnvelope[PayloadT]":
        if self.quality is DataQuality.GAP:
            if self.gap_reason is None:
                raise ValueError("gap quality requires gap_reason")
        else:
            if self.data is None:
                raise ValueError("non-gap quality requires data")
            if self.gap_reason is not None:
                raise ValueError("non-gap quality cannot carry gap_reason")
        return self


class CapabilityResult(NormalizedModel):
    available: bool
    source: NonBlankText
    latency_ms: FiniteFloat = Field(ge=0)
    sample_fields: list[NonBlankText] = Field(default_factory=list)
    error: NonBlankText | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> "CapabilityResult":
        if self.available and self.error is not None:
            raise ValueError("available capability cannot carry an error")
        if not self.available and self.error is None:
            raise ValueError("unavailable capability requires an error")
        return self


class ProviderCapabilities(NormalizedModel):
    security_catalog: CapabilityResult
    board_list: CapabilityResult
    board_members: CapabilityResult
    official_funds: CapabilityResult
    quotes: CapabilityResult
    transactions: CapabilityResult
    minute_data: CapabilityResult
    bars: CapabilityResult
    order_book: CapabilityResult


class QuoteSnapshot(NormalizedModel):
    symbol: MarketSymbol
    trade_date: date
    minute: Minute
    price: FiniteFloat = Field(ge=0)
    previous_close: FiniteFloat = Field(ge=0)
    change_pct: FiniteFloat
    volume: FiniteFloat = Field(ge=0)
    amount: FiniteFloat = Field(ge=0)


class OrderBookLevel(NormalizedModel):
    price: FiniteFloat = Field(ge=0)
    volume: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def validate_empty_level(self) -> "OrderBookLevel":
        if self.price == 0 and self.volume != 0:
            raise ValueError("zero-priced order-book level must have zero volume")
        return self


class OrderBook(NormalizedModel):
    symbol: MarketSymbol
    trade_date: date
    minute: Minute
    bids: list[OrderBookLevel] = Field(min_length=5, max_length=5)
    asks: list[OrderBookLevel] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_level_order(self) -> "OrderBook":
        bid_prices = self._populated_prices(self.bids)
        ask_prices = self._populated_prices(self.asks)
        if any(
            current <= following
            for current, following in zip(bid_prices, bid_prices[1:])
        ):
            raise ValueError("bid levels must be ordered from highest to lowest price")
        if any(
            current >= following
            for current, following in zip(ask_prices, ask_prices[1:])
        ):
            raise ValueError("ask levels must be ordered from lowest to highest price")
        return self

    @staticmethod
    def _populated_prices(levels: list[OrderBookLevel]) -> list[float]:
        populated_prices: list[float] = []
        found_empty_level = False
        for level in levels:
            if level.price == 0:
                found_empty_level = True
            elif found_empty_level:
                raise ValueError(
                    "populated levels must be contiguous before empty trailing levels"
                )
            else:
                populated_prices.append(level.price)
        return populated_prices


BarPeriod = Literal["day", "week", "month", "1m", "5m", "15m", "30m", "60m"]


class Bar(NormalizedModel):
    symbol: MarketSymbol
    period: BarPeriod
    timestamp: datetime
    open: FiniteFloat = Field(ge=0)
    high: FiniteFloat = Field(ge=0)
    low: FiniteFloat = Field(ge=0)
    close: FiniteFloat = Field(ge=0)
    volume: FiniteFloat = Field(ge=0)
    amount: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Bar":
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be greater than or equal to open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be less than or equal to open, high, and close")
        return self


class Transaction(NormalizedModel):
    symbol: MarketSymbol
    trade_date: date
    timestamp: datetime
    price: FiniteFloat = Field(ge=0)
    volume: FiniteFloat = Field(ge=0)
    amount: FiniteFloat = Field(ge=0)
    side: Literal["buy", "sell", "neutral"]

    @model_validator(mode="after")
    def validate_trade_date(self) -> "Transaction":
        if self.timestamp.date() != self.trade_date:
            raise ValueError("timestamp must fall on trade_date")
        return self


class TierPoint(NormalizedModel):
    delta: FiniteFloat = 0.0
    cumulative: FiniteFloat = 0.0
    source: NonBlankText
    quality: DataQuality


class FundFlow(NormalizedModel):
    main: TierPoint
    super: TierPoint
    large: TierPoint
    medium: TierPoint
    small: TierPoint

    @classmethod
    def zero(cls, source: str, quality: DataQuality) -> "FundFlow":
        def point() -> TierPoint:
            return TierPoint(source=source, quality=quality)

        return cls(main=point(), super=point(), large=point(), medium=point(), small=point())

    @classmethod
    def from_tiers(
        cls,
        *,
        super_delta: float,
        super_cum: float,
        large_delta: float,
        large_cum: float,
        medium_delta: float,
        medium_cum: float,
        small_delta: float,
        small_cum: float,
        source: str,
        quality: DataQuality,
    ) -> "FundFlow":
        def point(delta: float, cumulative: float) -> TierPoint:
            return TierPoint(
                delta=delta,
                cumulative=cumulative,
                source=source,
                quality=quality,
            )

        return cls(
            main=point(super_delta + large_delta, super_cum + large_cum),
            super=point(super_delta, super_cum),
            large=point(large_delta, large_cum),
            medium=point(medium_delta, medium_cum),
            small=point(small_delta, small_cum),
        )


class Security(NormalizedModel):
    symbol: NonBlankText
    code: NonBlankText
    name: NonBlankText
    market: NonBlankText
    active: bool = True


class Sector(NormalizedModel):
    sector_id: NonBlankText
    name: NonBlankText
    sector_type: NonBlankText


class Membership(NormalizedModel):
    sector_id: NonBlankText
    symbol: NonBlankText


class StockMinute(NormalizedModel):
    trade_date: date
    minute: Minute
    symbol: NonBlankText
    close: FiniteFloat = Field(ge=0)
    change_pct: FiniteFloat
    amount_delta: FiniteFloat = Field(ge=0)
    funds: FundFlow
    observed_at: datetime
    batch_id: NonBlankText


class SectorMinute(NormalizedModel):
    trade_date: date
    minute: Minute
    sector_id: NonBlankText
    change_pct: FiniteFloat
    member_count: int = Field(ge=0)
    funds: FundFlow
    observed_at: datetime
    batch_id: NonBlankText


class CollectionStatus(NormalizedModel):
    trade_date: date
    minute: Minute
    batch_id: NonBlankText
    catalog_version: NonBlankText
    expected_stocks: int = Field(ge=0)
    collected_stocks: int = Field(ge=0)
    expected_sectors: int = Field(ge=0)
    collected_sectors: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    coverage_pct: FiniteFloat = Field(ge=0, le=100)
    status: Literal["complete", "partial"]
    error_summary: str = ""

    @model_validator(mode="after")
    def validate_consistency(self) -> "CollectionStatus":
        if self.collected_stocks > self.expected_stocks:
            raise ValueError("collected_stocks cannot exceed expected_stocks")
        if self.collected_sectors > self.expected_sectors:
            raise ValueError("collected_sectors cannot exceed expected_sectors")
        expected_coverage = (
            round(self.collected_stocks / self.expected_stocks * 100.0, 4)
            if self.expected_stocks
            else 0.0
        )
        if self.coverage_pct != expected_coverage:
            raise ValueError("coverage_pct must match collected_stocks and expected_stocks")
        is_complete = self.coverage_pct >= 99.5 and self.collected_sectors == self.expected_sectors
        if (self.status == "complete") != is_complete:
            raise ValueError("status must match stock coverage and sector completeness")
        return self


class ProviderMinuteBatch(NormalizedModel):
    trade_date: date
    minute: Minute
    stocks: list[StockMinute]
    expected_stocks: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stocks(self) -> "ProviderMinuteBatch":
        if self.expected_stocks < len(self.stocks):
            raise ValueError("expected_stocks cannot be lower than the number of stocks")
        if len({stock.symbol for stock in self.stocks}) != len(self.stocks):
            raise ValueError("stocks cannot contain duplicate symbols")
        if any(
            stock.trade_date != self.trade_date or stock.minute != self.minute
            for stock in self.stocks
        ):
            raise ValueError("stocks must match the batch trade_date and minute")
        return self
