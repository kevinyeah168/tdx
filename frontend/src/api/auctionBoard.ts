import { apiGet } from '@/api/client'

export type AuctionBoardSort = 'ratio' | 'amount' | 'change' | 'volume' | 'price'
export type AuctionBoardPhase = 'waiting' | 'auction' | 'post_auction' | 'closed'
export type AuctionBoardScope = 'top' | 'market'

export interface AuctionBoardItem {
  rank: number
  symbol: string
  code: string
  name: string
  price: number | null
  change_pct: number | null
  volume_ratio: number | null
  amount: number | null
  volume: number | null
  open_net_inflow: number | null
}

export interface AuctionBoardResponse {
  trade_date: string
  fetched_at: string
  source: string
  data_kind: 'live' | 'snapshot'
  phase: AuctionBoardPhase
  sort: AuctionBoardSort
  scope: AuctionBoardScope
  q: string | null
  offset: number
  limit: number
  total: number
  items: AuctionBoardItem[]
}

export interface FetchAuctionBoardOptions {
  sort?: AuctionBoardSort
  scope?: AuctionBoardScope
  q?: string
  offset?: number
  limit?: number
  force?: boolean
}

export const AUCTION_BOARD_PAGE_SIZE = 100

export function fetchAuctionBoard(
  tradeDate: string,
  options: FetchAuctionBoardOptions = {},
): Promise<AuctionBoardResponse> {
  const params: Record<string, string> = { trade_date: tradeDate }
  if (options.sort) params.sort = options.sort
  if (options.scope) params.scope = options.scope
  if (options.q) params.q = options.q
  if (options.offset != null) params.offset = String(options.offset)
  if (options.limit != null) params.limit = String(options.limit)
  if (options.force) params.force = 'true'
  return apiGet<AuctionBoardResponse>('/api/v1/market/auction-board', params)
}
