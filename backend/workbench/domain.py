from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class DataQuality(str, Enum):
    OFFICIAL = "official"
    AGGREGATED = "aggregated"
    ESTIMATED = "estimated"
    CALIBRATED = "calibrated"
    STALE = "stale"
    GAP = "gap"


class TierPoint(BaseModel):
    delta: float = 0.0
    cumulative: float = 0.0
    source: str
    quality: DataQuality


class FundFlow(BaseModel):
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


class Security(BaseModel):
    symbol: str
    code: str
    name: str
    market: str
    active: bool = True


class Sector(BaseModel):
    sector_id: str
    name: str
    sector_type: str


class Membership(BaseModel):
    sector_id: str
    symbol: str


class StockMinute(BaseModel):
    trade_date: date
    minute: str = Field(pattern=r"^\d{2}:\d{2}$")
    symbol: str
    close: float
    change_pct: float
    amount_delta: float
    funds: FundFlow
    observed_at: datetime
    batch_id: str


class SectorMinute(BaseModel):
    trade_date: date
    minute: str = Field(pattern=r"^\d{2}:\d{2}$")
    sector_id: str
    change_pct: float
    member_count: int
    funds: FundFlow
    observed_at: datetime
    batch_id: str


class ProviderMinuteBatch(BaseModel):
    trade_date: date
    minute: str
    stocks: list[StockMinute]
    expected_stocks: int
    errors: list[str] = Field(default_factory=list)
