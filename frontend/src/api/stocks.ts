import { apiGet, apiPost, isApiNotFound } from '@/api/client'
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

export interface StockRankItem {
  symbol: string
  name: string
  main_cumulative: number
  change_pct: number
}

export interface StockRankResponse {
  trade_date: string
  minute: string
  items: StockRankItem[]
}

export function fetchStockRank(tradeDate: string, minute: string): Promise<StockRankResponse> {
  return apiGet<StockRankResponse>('/api/v1/stocks/rank', {
    date: tradeDate,
    minute,
  })
}

export interface StockCatalogItem {
  symbol: string
  name: string
}

export function fetchStockCatalog(): Promise<{ items: StockCatalogItem[] }> {
  return apiGet<{ items: StockCatalogItem[] }>('/api/v1/stocks/catalog')
}

export interface StockResolveItem {
  symbol: string
  name: string
}

export interface StockResolveResponse {
  resolved: StockResolveItem[]
  unresolved: string[]
}

export async function resolveStockSymbols(inputs: string[]): Promise<StockResolveResponse> {
  const response = await fetch('/api/v1/stocks/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ inputs }),
  })
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<StockResolveResponse>
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

export interface StockGrayFlowPoint {
  minute: string
  dark_cumulative: number
  open_cumulative?: number | null
  total_cumulative?: number | null
  source?: string | null
}

export interface StockGrayFlowPayload {
  symbol: string
  latest_complete_minute: string
  points: StockGrayFlowPoint[]
}

export function fetchStockGrayFlow(symbol: string, tradeDate: string): Promise<StockGrayFlowPayload> {
  return apiGet<StockGrayFlowPayload>(`/api/v1/stocks/${symbol}/gray-flow`, {
    date: tradeDate,
  })
}

export interface StockFundFlowBatchResponse {
  trade_date: string
  items: Array<SectorFundFlowPayload & { symbol: string }>
}

export interface StockGrayFlowBatchResponse {
  trade_date: string
  items: StockGrayFlowPayload[]
}

export async function fetchStockFundFlowBatch(
  symbols: string[],
  tradeDate: string,
  opts?: { tiers?: string },
): Promise<StockFundFlowBatchResponse> {
  if (!symbols.length) {
    return { trade_date: tradeDate, items: [] }
  }
  const query: Record<string, string> = { date: tradeDate }
  if (opts?.tiers) query.tiers = opts.tiers
  try {
    return await apiPost<StockFundFlowBatchResponse>(
      '/api/v1/stocks/fund-flow/batch',
      { ids: symbols },
      query,
    )
  } catch (error) {
    if (!isApiNotFound(error)) throw error
    const items = (
      await Promise.all(
        symbols.map(async (symbol) => {
          try {
            return await fetchStockFundFlow(symbol, tradeDate)
          } catch {
            return null
          }
        }),
      )
    ).filter((item): item is StockFundFlowBatchResponse['items'][number] => item != null)
    return { trade_date: tradeDate, items }
  }
}

export async function fetchStockGrayFlowBatch(
  symbols: string[],
  tradeDate: string,
): Promise<StockGrayFlowBatchResponse> {
  if (!symbols.length) {
    return { trade_date: tradeDate, items: [] }
  }
  try {
    return await apiPost<StockGrayFlowBatchResponse>(
      '/api/v1/stocks/gray-flow/batch',
      { ids: symbols },
      { date: tradeDate },
    )
  } catch (error) {
    if (!isApiNotFound(error)) throw error
    const items = (
      await Promise.all(
        symbols.map(async (symbol) => {
          try {
            return await fetchStockGrayFlow(symbol, tradeDate)
          } catch {
            return null
          }
        }),
      )
    ).filter((item): item is StockGrayFlowPayload => item != null)
    return { trade_date: tradeDate, items }
  }
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
