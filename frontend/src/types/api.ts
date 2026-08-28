export interface QueryMetadata {
  catalog_version: string | null
  batch_id: string | null
  coverage_pct: number | null
  stale: boolean
  source: string | null
}

export interface MarketOverview {
  trade_date: string
  minute: string | null
  security_count: number
  sector_count: number
  latest_complete_minute: string | null
  latest_available_minute?: string | null
  metadata: QueryMetadata
}

export interface SearchResultItem {
  symbol: string
  name: string
  market: string
}

export interface SearchResponse {
  query: string
  results: SearchResultItem[]
  metadata: QueryMetadata
}

export interface SectorSummary {
  sector_id: string
  name: string
  sector_type: string
  member_count: number
}

export interface SectorListResponse {
  items: SectorSummary[]
  metadata: QueryMetadata
}
