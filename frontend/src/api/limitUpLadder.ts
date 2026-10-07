import { apiGet } from '@/api/client'

export interface LimitUpLadderItem {
  symbol: string
  code: string
  name: string
  price: number | null
  change_pct: number | null
  board_days: number
  first_seal_time: string | null
  last_seal_time: string | null
  seal_amount: number | null
  broken_count: number | null
  industry: string | null
  turnover_rate: number | null
  limit_stats: string | null
}

export interface LimitUpLadderTier {
  board_days: number
  label: string
  count: number
  items: LimitUpLadderItem[]
}

export interface LimitUpLadderSummary {
  limit_up_count: number
  max_board: number
  broken_count: number
  break_rate_pct: number | null
  first_board_count: number
  multi_board_count: number
}

export interface LimitUpLadderResponse {
  trade_date: string
  fetched_at: string
  source: string
  data_kind: 'live' | 'snapshot'
  summary: LimitUpLadderSummary
  tiers: LimitUpLadderTier[]
}

export function fetchLimitUpLadder(
  tradeDate: string,
  options: { force?: boolean } = {},
): Promise<LimitUpLadderResponse> {
  const params: Record<string, string> = { trade_date: tradeDate }
  if (options.force) params.force = 'true'
  return apiGet<LimitUpLadderResponse>('/api/v1/market/limit-up/ladder', params)
}
