from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

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


Minute = Annotated[str, AfterValidator(validate_minute)]
NonBlankText = Annotated[str, AfterValidator(validate_nonblank_text)]


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
