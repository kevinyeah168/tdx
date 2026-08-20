from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated

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


Minute = Annotated[str, AfterValidator(validate_minute)]


class NormalizedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataQuality(str, Enum):
    OFFICIAL = "official"
    AGGREGATED = "aggregated"
    ESTIMATED = "estimated"
    CALIBRATED = "calibrated"
    STALE = "stale"
    GAP = "gap"


class TierPoint(NormalizedModel):
    delta: FiniteFloat = 0.0
    cumulative: FiniteFloat = 0.0
    source: str
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
    symbol: str
    code: str
    name: str
    market: str
    active: bool = True


class Sector(NormalizedModel):
    sector_id: str
    name: str
    sector_type: str


class Membership(NormalizedModel):
    sector_id: str
    symbol: str


class StockMinute(NormalizedModel):
    trade_date: date
    minute: Minute
    symbol: str
    close: FiniteFloat = Field(ge=0)
    change_pct: FiniteFloat
    amount_delta: FiniteFloat = Field(ge=0)
    funds: FundFlow
    observed_at: datetime
    batch_id: str


class SectorMinute(NormalizedModel):
    trade_date: date
    minute: Minute
    sector_id: str
    change_pct: FiniteFloat
    member_count: int = Field(ge=0)
    funds: FundFlow
    observed_at: datetime
    batch_id: str


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
