export interface BoardItem {
  id: string
  name: string
  change_pct?: number | null
  cum_main?: number | null
  sector_type?: string | null
  /** Whether this sector is drawn on the home chart (max 30). */
  chart_visible?: boolean
  /** 个股榜单用：净比(%) = 主力净流入 / 自由流通市值 * 100 */
  main_net_ratio?: number | null
  /** 净比(均)(%) = 主力净流入 / (自由流通股本×均价) * 100 */
  main_net_ratio_avg?: number | null
  /** 自由流通市值（元），用于随明盘重算净比 */
  free_float_market_cap?: number | null
  /** 均价口径自由流通市值（元） */
  free_float_market_cap_avg?: number | null
}

export interface FlowSeries {
  id: string
  name: string
  symbol?: string
  sector_type?: string | null
  cum_main: number
  change_pct?: number | null
  /** 个股净比(%) = 主力净流入 / 自由流通市值 * 100 */
  main_net_ratio?: number | null
  /** 净比(均)(%) = 主力净流入 / (自由流通股本×均价) * 100 */
  main_net_ratio_avg?: number | null
  /** 自由流通市值（元） */
  free_float_market_cap?: number | null
  /** 均价口径自由流通市值（元） */
  free_float_market_cap_avg?: number | null
  values: (number | null)[]
  cum_tick?: number
  cum_mac?: number
  price?: number | null
  price_values?: (number | null)[]
  /** 分时均价（VWAP） */
  avg_price_values?: (number | null)[]
  /** 暗盘累计净流入（元），与 values 同轴 */
  gray_values?: (number | null)[]
  /** 暗盘最新累计净流入（元） */
  cum_gray?: number | null
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
  searchHint?: string
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

export type BoardCatalogType = 'ALL' | 'HY' | 'GN' | 'HY2' | 'IDX'

export type ViewTab = 'sector' | 'stock'
