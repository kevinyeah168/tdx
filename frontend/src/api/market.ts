import { apiGet } from '@/api/client'
import type { MarketOverview, SearchResponse } from '@/types/api'

export function fetchMarketOverview(tradeDate: string): Promise<MarketOverview> {
  return apiGet<MarketOverview>('/api/v1/market/overview', { date: tradeDate })
}

export function searchSecurities(query: string): Promise<SearchResponse> {
  return apiGet<SearchResponse>('/api/v1/market/search', { q: query })
}
