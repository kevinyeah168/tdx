import { apiGet } from '@/api/client'

export type HotStockBoard = 'popularity' | 'surge'
export type HotStockSource = 'eastmoney' | 'ths' | 'both'
export type HotBoardType = 'concept' | 'industry'

export interface HotStockItem {
  rank: number
  symbol: string
  code: string
  name: string
  price: number | null
  change_pct: number | null
  rank_change: number | null
  hot_value: number | null
  source: string
}

export interface HotStockListResponse {
  board: HotStockBoard
  source: HotStockSource
  fetched_at: string
  items: HotStockItem[]
  eastmoney: HotStockItem[] | null
  ths: HotStockItem[] | null
}

export interface HotBoardItem {
  rank: number
  board_code: string
  name: string
  change_pct: number | null
  hot_value: number | null
  rank_change: number | null
  source: string
}

export interface HotBoardListResponse {
  board_type: HotBoardType
  fetched_at: string
  source: string
  items: HotBoardItem[]
}

export function fetchHotStocks(
  board: HotStockBoard,
  source: HotStockSource,
): Promise<HotStockListResponse> {
  return apiGet<HotStockListResponse>('/api/v1/market/hot/stocks', { board, source })
}

export function fetchHotBoards(boardType: HotBoardType): Promise<HotBoardListResponse> {
  return apiGet<HotBoardListResponse>('/api/v1/market/hot/boards', { type: boardType })
}
