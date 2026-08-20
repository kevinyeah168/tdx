export interface BoardItem {
  id: string
  name: string
  change_pct?: number | null
}

export interface FlowSeries {
  id: string
  name: string
  symbol?: string
  cum_main: number
  change_pct?: number | null
  values: (number | null)[]
  cum_tick?: number
  cum_mac?: number
  price?: number | null
}

export type SectorSeries = FlowSeries

export type StockSeries = FlowSeries

export interface WatchItem {
  symbol: string
  name?: string
  cum_main?: number | null
  cum_net?: number | null
  cum_tick?: number | null
  cum_mac?: number | null
  quote?: {
    change_pct?: number | null
    price?: number | null
  } | null
}

export interface BoardPayload {
  updated_at: string | null
  error: string | null
  disclaimer: string
  host: string
  board_type: string
  sector_mode: string
  selected_boards: BoardItem[]
  stock_mode: string
  selected_stocks: BoardItem[]
  watchlist: WatchItem[]
  timeline: string[]
  sector_series: SectorSeries[]
  stock_timeline: string[]
  stock_series: StockSeries[]
  stock_view_date?: string | null
  sector_view_date?: string | null
  stock_intraday_dates?: string[]
  sector_intraday_dates?: string[]
  intraday_retention_days?: number
  trading_session?: {
    tradeDate?: string
    currentMinute?: string
    marketStatus?: string
    sessionStatus?: string
    isTradingDay?: boolean
    message?: string
  } | null
}

export interface StockDetail {
  symbol?: string
  trade_date?: string | null
  quote?: WatchItem['quote']
  fund_flow: Array<{
    time: string
    cum_main?: number | null
    cum_net?: number | null
    price?: number | null
    change_pct?: number | null
  }>
}

export interface CatalogResponse {
  boards: BoardItem[]
  type?: string
}

export interface SelectedBoardsResponse {
  boards: BoardItem[]
}

export interface StockCatalogResponse {
  stocks: BoardItem[]
  total?: number
}

export interface SelectedStocksResponse {
  stocks: BoardItem[]
}

export type BoardCatalogType = 'HY' | 'GN' | 'HY2'

export type ViewTab = 'sector' | 'stock'
