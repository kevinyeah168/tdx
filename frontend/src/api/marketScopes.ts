import { apiGet } from '@/api/client'

export type MarketScopeKey = 'hs' | 'sh' | 'kc' | 'sz' | 'cy'

export interface MarketScopeCurvePoint {
  minute: string
  main_cumulative: number
  main_delta: number
  change_pct?: number | null
}

export interface MarketScopeSeries {
  scope: MarketScopeKey
  label: string
  latest_complete_minute: string | null
  change_pct?: number | null
  points: MarketScopeCurvePoint[]
}

export interface MarketScopeSeriesResponse {
  trade_date: string
  items: MarketScopeSeries[]
}

export const MARKET_SCOPE_ORDER: MarketScopeKey[] = ['hs', 'sh', 'kc', 'sz', 'cy']

export function fetchMarketScopeMinutes(
  tradeDate: string,
  opts?: { minute?: string | null; scopes?: MarketScopeKey[] },
): Promise<MarketScopeSeriesResponse> {
  const params: Record<string, string> = {
    date: tradeDate,
    scopes: opts?.scopes?.join(',') ?? MARKET_SCOPE_ORDER.join(','),
  }
  if (opts?.minute) params.minute = opts.minute
  return apiGet<MarketScopeSeriesResponse>('/api/v1/market/scopes/minutes', params)
}
