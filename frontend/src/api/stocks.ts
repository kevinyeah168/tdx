import { apiGet } from '@/api/client'
import type { SectorFundFlowPayload } from '@/api/sectors'

export interface BarPoint {
  timestamp: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
}

export interface StockBarsPayload {
  symbol: string
  period: 'day' | 'week' | 'month' | '1m' | '5m' | '15m' | '30m' | '60m'
  bars: BarPoint[]
}

export interface StockDetail {
  symbol: string
  code: string
  name: string
  market: string
  active: boolean
}

export interface StockSectorItem {
  sector_id: string
  name: string
  sector_type: string
}

export function fetchStockDetail(symbol: string): Promise<StockDetail> {
  return apiGet<StockDetail>(`/api/v1/stocks/${symbol}`)
}

export function fetchStockSectors(symbol: string): Promise<{ items: StockSectorItem[] }> {
  return apiGet<{ items: StockSectorItem[] }>(`/api/v1/stocks/${symbol}/sectors`)
}

export interface StockIntradayPoint {
  minute: string
  close: number
  change_pct: number
  main_cumulative: number
}

export interface StockIntradayPayload {
  symbol: string
  trade_date: string
  points: StockIntradayPoint[]
}

export function fetchStockFundFlow(symbol: string, tradeDate: string): Promise<SectorFundFlowPayload & { symbol: string }> {
  return apiGet<SectorFundFlowPayload & { symbol: string }>(`/api/v1/stocks/${symbol}/fund-flow`, {
    date: tradeDate,
  })
}

export function fetchStockIntraday(symbol: string, tradeDate: string): Promise<StockIntradayPayload> {
  return apiGet<StockIntradayPayload>(`/api/v1/stocks/${symbol}/intraday`, {
    date: tradeDate,
  })
}

export function fetchStockBars(
  symbol: string,
  period: StockBarsPayload['period'] = 'day',
  count = 60,
): Promise<StockBarsPayload> {
  return apiGet<StockBarsPayload>(`/api/v1/stocks/${symbol}/bars`, {
    period,
    count: String(count),
  })
}
