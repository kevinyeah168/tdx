from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QueryMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    catalog_version: str | None = None
    batch_id: str | None = None
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    stale: bool = False
    source: str | None = None


class MarketOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    minute: str | None
    security_count: int = Field(ge=0)
    sector_count: int = Field(ge=0)
    latest_complete_minute: str | None = None
    latest_available_minute: str | None = None
    metadata: QueryMetadata


class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str
    name: str
    market: str


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str
    results: list[SearchResultItem]
    metadata: QueryMetadata


class SectorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str
    name: str
    sector_type: str
    member_count: int = Field(ge=0)


class SectorListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[SectorSummary]
    metadata: QueryMetadata


class SectorMemberRankItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str
    name: str
    main_cumulative: float
    change_pct: float
    free_float_market_cap: float | None = None
    main_net_ratio: float | None = None
    free_float_market_cap_avg: float | None = None
    main_net_ratio_avg: float | None = None


class SectorMemberRankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str
    trade_date: str
    minute: str
    items: list[SectorMemberRankItem]
    metadata: QueryMetadata


class StockRankItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str
    name: str
    main_cumulative: float
    change_pct: float


class StockRankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    minute: str
    items: list[StockRankItem]
    metadata: QueryMetadata


class CatalogMemberItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str
    name: str


class SectorCatalogMembersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str
    items: list[CatalogMemberItem]
    metadata: QueryMetadata


class SectorRankItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str
    name: str
    sector_type: str
    main_cumulative: float
    change_pct: float


class SectorRankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    minute: str
    items: list[SectorRankItem]
    metadata: QueryMetadata


class SectorSnapshotItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str
    main_cumulative: float
    change_pct: float


class SectorSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    minute: str
    items: list[SectorSnapshotItem]
    metadata: QueryMetadata


class SectorBreadthCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    limit_up: int = Field(ge=0)
    limit_down: int = Field(ge=0)
    up: int = Field(ge=0)
    down: int = Field(ge=0)
    flat: int = Field(ge=0)
    sampled: int = Field(ge=0)
    total_members: int = Field(ge=0)


class SectorBreadthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sector_id: str
    trade_date: str
    minute: str
    counts: SectorBreadthCounts
    limit_up: list[SectorMemberRankItem]
    limit_down: list[SectorMemberRankItem]
    up: list[SectorMemberRankItem]
    down: list[SectorMemberRankItem]
    metadata: QueryMetadata
