import type {
  BoardCatalogType,
  BoardItem,
  BoardPayload,
  CatalogResponse,
  SelectedBoardsResponse,
  StockCatalogResponse,
  SelectedStocksResponse,
  StockDetail,
  FlowSeries,
} from '@/types/board'
import type { MarketOverview } from '@/types/api'
import type {
  WorkbenchSectorChartsPartial,
  WorkbenchSectorGrayPartial,
} from '@/api/workbenchBoard'

const WORKBENCH_MODE = import.meta.env.VITE_WORKBENCH === 'true'

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<T>
}

function alignField(
  flowRows: Array<{ time: string; cum_main?: number | null; cum_net?: number | null }>,
  timeline: string[],
  field: 'cum_main' | 'cum_net' = 'cum_main',
): (number | null)[] {
  const byT: Record<string, number> = {}
  for (const row of flowRows) {
    byT[row.time] = Number(row[field] ?? row.cum_net ?? 0)
  }
  let last: number | null = null
  return timeline.map((t) => {
    if (t in byT) last = byT[t]
    return last
  })
}

function buildStockSeriesFromWatchlist(board: Partial<BoardPayload>): {
  timeline: string[]
  series: FlowSeries[]
} {
  const watchlist = board.watchlist || []
  const stockFlows = (board as BoardPayload & { stock_flows?: Record<string, StockDetail['fund_flow']> }).stock_flows
  const timeSet = new Set<string>()

  for (const row of watchlist) {
    const flow = stockFlows?.[row.symbol]
    if (flow) {
      for (const pt of flow) timeSet.add(pt.time)
    }
  }

  const timeline = [...timeSet].sort()
  const series = watchlist.map((row) => {
    const flow = stockFlows?.[row.symbol] || []
    return {
      id: row.symbol,
      symbol: row.symbol,
      name: row.name || row.symbol,
      change_pct: row.quote?.change_pct ?? null,
      cum_main: Number(row.cum_main ?? row.cum_net ?? 0),
      values: alignField(flow, timeline),
    }
  })

  return { timeline, series }
}

export function normalizeBoard(data: Partial<BoardPayload>): BoardPayload {
  const sector_series = data.sector_series ?? []
  const timeline = data.timeline ?? []
  let stock_timeline = data.stock_timeline ?? []
  let stock_series = data.stock_series ?? []

  if (!stock_series.length && (data.watchlist?.length ?? 0) > 0) {
    const built = buildStockSeriesFromWatchlist(data)
    stock_timeline = built.timeline
    stock_series = built.series
  }

  return {
    updated_at: data.updated_at ?? null,
    error: data.error ?? null,
    disclaimer: data.disclaimer ?? '',
    host: data.host ?? '',
    board_type: data.board_type ?? 'HY',
    sector_mode: data.sector_mode ?? 'auto',
    selected_boards: data.selected_boards ?? [],
    imported_sector_boards: data.imported_sector_boards ?? [],
    stock_mode: data.stock_mode ?? 'empty',
    selected_stocks: data.selected_stocks ?? [],
    watchlist: data.watchlist ?? [],
    timeline,
    sector_series,
    stock_timeline,
    stock_series,
    stock_view_date: data.stock_view_date ?? null,
    sector_view_date: data.sector_view_date ?? null,
    stock_intraday_dates: data.stock_intraday_dates ?? [],
    sector_intraday_dates: data.sector_intraday_dates ?? [],
    intraday_retention_days: data.intraday_retention_days ?? 15,
    trading_session: data.trading_session ?? null,
  }
}

export async function fetchBoard(opts?: {
  stockDate?: string | null
  sectorDate?: string | null
  sectorSourceMode?: 'auto' | 'selected'
  stockSourceMode?: 'linkage' | 'selected'
  linkageSectorId?: string | null
  linkageSectorName?: string | null
  autoSectorCount?: number
  linkageTopK?: number
  replayMinute?: string | null
  replayDates?: string[]
  marketOverview?: MarketOverview | null
  onSectorChartsReady?: (partial: WorkbenchSectorChartsPartial) => void
  onSectorGrayReady?: (partial: WorkbenchSectorGrayPartial) => void
}): Promise<BoardPayload> {
  if (WORKBENCH_MODE) {
    const { fetchWorkbenchBoard } = await import('@/api/workbenchBoard')
    return fetchWorkbenchBoard(opts)
  }
  const params = new URLSearchParams()
  if (opts?.stockDate) params.set('stock_date', opts.stockDate)
  if (opts?.sectorDate) params.set('sector_date', opts.sectorDate)
  const qs = params.toString()
  const res = await fetch(qs ? `/api/board?${qs}` : '/api/board')
  const data = await parseJson<Partial<BoardPayload>>(res)
  const normalized = normalizeBoard(data)

  const session = normalized.trading_session
  const stockEmpty = !normalized.stock_series.some((s) => s.values.some((v) => v != null))
  const isToday = normalized.stock_view_date === session?.tradeDate
  const canEnrich = session?.sessionStatus === 'open' && isToday

  if (stockEmpty && canEnrich) {
    const enriched = await enrichStockSeries(normalized, opts?.stockDate || normalized.stock_view_date)
    return enriched
  }

  return normalized
}

async function enrichStockSeries(board: BoardPayload, stockDate?: string | null): Promise<BoardPayload> {
  const timeSet = new Set<string>(board.stock_timeline)
  const flowMap: Record<string, StockDetail['fund_flow']> = {}

  await Promise.all(
    board.watchlist.map(async (row) => {
      const detail = await fetchStock(row.symbol, stockDate)
      if (!detail?.fund_flow?.length) return
      flowMap[row.symbol] = detail.fund_flow
      for (const pt of detail.fund_flow) timeSet.add(pt.time)
    }),
  )

  const timeline = [...timeSet].sort()
  const stock_series = board.watchlist.map((row) => {
    const flow = flowMap[row.symbol] || []
    return {
      id: row.symbol,
      symbol: row.symbol,
      name: row.name || row.symbol,
      change_pct: row.quote?.change_pct ?? null,
      cum_main: Number(row.cum_main ?? row.cum_net ?? 0),
      values: alignField(flow, timeline),
    }
  })

  return { ...board, stock_timeline: timeline, stock_series }
}

export async function fetchBoardCatalog(
  type: BoardCatalogType,
  q = '',
  limit = 300,
): Promise<CatalogResponse> {
  if (WORKBENCH_MODE) {
    const { fetchWorkbenchBoardCatalog } = await import('@/api/workbenchBoard')
    return fetchWorkbenchBoardCatalog(type, q, limit)
  }
  const params = new URLSearchParams({ type, q, limit: String(limit) })
  const res = await fetch(`/api/board-catalog?${params}`)
  return parseJson<CatalogResponse>(res)
}

export async function fetchSelectedBoards(): Promise<SelectedBoardsResponse> {
  if (WORKBENCH_MODE) {
    const { fetchWorkbenchSelectedBoards } = await import('@/api/workbenchBoard')
    return fetchWorkbenchSelectedBoards()
  }
  const res = await fetch('/api/selected-boards')
  return parseJson<SelectedBoardsResponse>(res)
}

export async function saveSelectedBoards(boards: BoardItem[]): Promise<void> {
  if (WORKBENCH_MODE) {
    const { saveWorkbenchSelectedBoards } = await import('@/api/workbenchBoard')
    return saveWorkbenchSelectedBoards(boards)
  }
  await fetch('/api/selected-boards', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ boards }),
  })
}

export async function fetchStockCatalog(q = '', limit = 50): Promise<StockCatalogResponse> {
  if (WORKBENCH_MODE) {
    const { fetchWorkbenchStockCatalog } = await import('@/api/workbenchBoard')
    return fetchWorkbenchStockCatalog(q, limit)
  }
  const params = new URLSearchParams({ q, limit: String(limit) })
  const res = await fetch(`/api/stock-catalog?${params}`)
  return parseJson<StockCatalogResponse>(res)
}

export async function fetchSelectedStocks(): Promise<SelectedStocksResponse> {
  if (WORKBENCH_MODE) {
    const { fetchWorkbenchSelectedStocks } = await import('@/api/workbenchBoard')
    return fetchWorkbenchSelectedStocks()
  }
  const res = await fetch('/api/selected-stocks')
  return parseJson<SelectedStocksResponse>(res)
}

export async function saveSelectedStocks(stocks: BoardItem[]): Promise<void> {
  if (WORKBENCH_MODE) {
    const { saveWorkbenchSelectedStocks } = await import('@/api/workbenchBoard')
    return saveWorkbenchSelectedStocks(stocks)
  }
  await fetch('/api/selected-stocks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stocks }),
  })
}

export async function refreshBoardData(): Promise<void> {
  if (WORKBENCH_MODE) {
    const { refreshWorkbenchBoardData } = await import('@/api/workbenchBoard')
    return refreshWorkbenchBoardData()
  }
  await fetch('/api/refresh', { method: 'POST' })
}

export async function fetchStock(symbol: string, date?: string | null): Promise<StockDetail | null> {
  if (WORKBENCH_MODE) {
    const { fetchWorkbenchStock } = await import('@/api/workbenchBoard')
    return fetchWorkbenchStock(symbol, date)
  }
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  const qs = params.toString()
  const url = qs
    ? `/api/stock/${encodeURIComponent(symbol)}?${qs}`
    : `/api/stock/${encodeURIComponent(symbol)}`
  const res = await fetch(url)
  if (!res.ok) return null
  return parseJson<StockDetail>(res)
}
