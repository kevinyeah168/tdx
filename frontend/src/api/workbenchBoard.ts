import { fetchMarketOverview, searchSecurities } from '@/api/market'
import { fetchReplayDates, fetchReplayMinutes } from '@/api/replay'
import { fetchCollectionTargets } from '@/api/settings'
import {
  fetchSectorCatalogMembers,
  fetchSectorFundFlow,
  fetchSectorMembers,
  fetchSectorRank,
  fetchSectors,
  type CurvePoint,
} from '@/api/sectors'
import { fetchStockFundFlow, fetchStockIntraday } from '@/api/stocks'
import type {
  BoardCatalogType,
  BoardItem,
  BoardPayload,
  CatalogResponse,
  FlowSeries,
  SelectedBoardsResponse,
  SelectedStocksResponse,
  StockCatalogResponse,
  StockDetail,
} from '@/types/board'
import { TRADING_MINUTES, withoutPrematureClosingPoint, filterLiveReplayMinutes, capLiveReplayMinute } from '@/utils/tradingTimeline'
import { legacySectorSearchHint, isClassicIndexCodeQuery } from '@/utils/sectorCodeAliases'
import { inferSectorTypeFromId, resolveSectorType } from '@/utils/format'

const SELECTED_BOARDS_KEY = 'workbench-selected-boards'
const SELECTED_STOCKS_KEY = 'workbench-selected-stocks'
const SECTOR_SOURCE_MODE_KEY = 'workbench-sector-source-mode'
const STOCK_SOURCE_MODE_KEY = 'workbench-stock-source-mode'
const AUTO_SECTOR_COUNT_KEY = 'workbench-auto-sector-count'
const LINKAGE_TOP_K_KEY = 'workbench-linkage-top-k'

export type SectorSourceMode = 'auto' | 'selected'
export type StockSourceMode = 'linkage' | 'selected'

export const DEFAULT_AUTO_SECTOR_COUNT = 20
export const DEFAULT_LINKAGE_TOP_K = 30

const BOARD_TYPE_FILTER: Partial<Record<BoardCatalogType, string>> = {
  HY: 'industry',
  GN: 'concept',
  HY2: 'industry2',
  IDX: 'classic_index',
}

function previousTradingMinute(minute: string): string | null {
  const idx = TRADING_MINUTES.indexOf(minute)
  return idx > 0 ? TRADING_MINUTES[idx - 1]! : null
}

function readStorage<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeStorage(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value))
}

export function loadSectorSourceMode(): SectorSourceMode {
  const mode = readStorage<SectorSourceMode>(SECTOR_SOURCE_MODE_KEY)
  return mode === 'selected' ? 'selected' : 'auto'
}

export function saveSectorSourceMode(mode: SectorSourceMode) {
  writeStorage(SECTOR_SOURCE_MODE_KEY, mode)
}

export function loadStockSourceMode(): StockSourceMode {
  const mode = readStorage<StockSourceMode>(STOCK_SOURCE_MODE_KEY)
  return mode === 'selected' ? 'selected' : 'linkage'
}

export function saveStockSourceMode(mode: StockSourceMode) {
  writeStorage(STOCK_SOURCE_MODE_KEY, mode)
}

export function loadAutoSectorCount(): number {
  const value = readStorage<number>(AUTO_SECTOR_COUNT_KEY)
  if (typeof value === 'number' && value >= 4 && value <= 50) return value
  return DEFAULT_AUTO_SECTOR_COUNT
}

export function saveAutoSectorCount(count: number) {
  writeStorage(AUTO_SECTOR_COUNT_KEY, count)
}

export function loadLinkageTopK(): number {
  const value = readStorage<number>(LINKAGE_TOP_K_KEY)
  if (typeof value === 'number' && value >= 5 && value <= 100) return value
  return DEFAULT_LINKAGE_TOP_K
}

export function saveLinkageTopK(topK: number) {
  writeStorage(LINKAGE_TOP_K_KEY, topK)
}

export function loadSelectedBoards(): BoardItem[] {
  return readStorage<BoardItem[]>(SELECTED_BOARDS_KEY) ?? []
}

export function saveSelectedBoardsLocal(boards: BoardItem[]) {
  writeStorage(SELECTED_BOARDS_KEY, boards)
}

export function loadSelectedStocks(): BoardItem[] {
  return readStorage<BoardItem[]>(SELECTED_STOCKS_KEY) ?? []
}

export function saveSelectedStocksLocal(stocks: BoardItem[]) {
  writeStorage(SELECTED_STOCKS_KEY, stocks)
}

const DEFAULT_SECTOR_NAMES = [
  '5G概念',
  '通信设备',
  'CPO概念',
  '有色金属',
  '人工智能',
  '半导体',
  '新能源车',
  '光伏概念',
]

function toBoardItem(item: {
  sector_id: string
  name: string
  sector_type?: string
}): BoardItem {
  return {
    id: item.sector_id,
    name: item.name,
    sector_type: item.sector_type ?? inferSectorTypeFromId(item.sector_id),
  }
}

export function enrichBoardItems(
  boards: BoardItem[],
  catalog: { sector_id: string; name: string; sector_type: string }[],
): BoardItem[] {
  const byId = new Map(catalog.map((item) => [item.sector_id, item]))
  return boards.map((board) => {
    const hit = byId.get(board.id)
    return {
      ...board,
      name: hit?.name ?? board.name,
      sector_type: resolveSectorType({
        sector_type: board.sector_type ?? hit?.sector_type,
        id: board.id,
      }),
    }
  })
}

function pickDefaultBoards(items: { sector_id: string; name: string; sector_type: string }[]): BoardItem[] {
  const picked: BoardItem[] = []
  for (const name of DEFAULT_SECTOR_NAMES) {
    const hit = items.find((item) => item.name === name || item.name.includes(name))
    if (hit && !picked.some((b) => b.id === hit.sector_id)) {
      picked.push(toBoardItem(hit))
    }
    if (picked.length >= 8) break
  }
  for (const item of items) {
    if (picked.length >= 8) break
    if (item.sector_type === 'concept' && !picked.some((b) => b.id === item.sector_id)) {
      picked.push(toBoardItem(item))
    }
  }
  if (!picked.length && items.length > 0) {
    return items.slice(0, 8).map((item) => toBoardItem(item))
  }
  return picked
}

interface RawSeries {
  id: string
  name: string
  symbol?: string
  sector_type?: string | null
  cum_main: number
  change_pct: number | null
  timeline: string[]
  values: (number | null)[]
  price_values?: (number | null)[]
}

function mergeIntradayPrices(
  points: CurvePoint[],
  intraday: { minute: string; close: number; change_pct?: number }[],
): CurvePoint[] {
  if (!intraday.length) return points
  const priceByMinute = new Map(intraday.map((row) => [row.minute, row]))
  return points.map((point) => {
    if (point.close != null && Number.isFinite(point.close)) return point
    const row = priceByMinute.get(point.minute)
    if (!row) return point
    return {
      ...point,
      close: row.close,
      change_pct: row.change_pct ?? point.change_pct,
    }
  })
}

function buildRawSeries(
  id: string,
  name: string,
  points: CurvePoint[],
  changePct: number | null,
  extra?: { symbol?: string; sector_type?: string | null },
): RawSeries | null {
  const livePoints = withoutPrematureClosingPoint(points)
  if (!livePoints.length) return null

  let timeline = livePoints.map((point) => point.minute)
  let values = livePoints.map((point) => point.values.main?.cumulative ?? null)
  let price_values = livePoints.map((point) =>
    point.close != null && Number.isFinite(point.close) ? point.close : null,
  )

  if (timeline.length === 1 && values[0] != null) {
    const prev = previousTradingMinute(timeline[0]!)
    if (prev) {
      timeline = [prev, timeline[0]!]
      values = [0, values[0]]
      price_values = [null, price_values[0] ?? null]
    }
  }

  const last = livePoints[livePoints.length - 1]!
  const hasPrice = price_values.some((v) => v != null)
  return {
    id,
    name,
    symbol: extra?.symbol,
    sector_type: extra?.sector_type ?? inferSectorTypeFromId(id),
    cum_main: last.values.main?.cumulative ?? 0,
    change_pct: changePct,
    timeline,
    values,
    price_values: hasPrice ? price_values : undefined,
  }
}

function extendSeriesWithLivePoint(
  series: RawSeries,
  minute: string,
  liveMain: number,
  changePct: number | null,
): RawSeries {
  const lastIndex = series.timeline.length - 1
  const lastMinute = lastIndex >= 0 ? series.timeline[lastIndex] : null
  if (lastMinute === minute) {
    const values = [...series.values]
    values[lastIndex] = liveMain
    return {
      ...series,
      cum_main: liveMain,
      change_pct: changePct ?? series.change_pct,
      values,
    }
  }
  if (lastMinute && minute > lastMinute) {
    return {
      ...series,
      cum_main: liveMain,
      change_pct: changePct ?? series.change_pct,
      timeline: [...series.timeline, minute],
      values: [...series.values, liveMain],
    }
  }
  return {
    ...series,
    cum_main: liveMain,
    change_pct: changePct ?? series.change_pct,
  }
}

function mergeTimeline(items: RawSeries[]): string[] {
  const minutes = new Set<string>()
  for (const item of items) {
    for (const minute of item.timeline) minutes.add(minute)
  }
  return [...minutes].sort()
}

function alignToTimeline(item: RawSeries, boardTimeline: string[]): FlowSeries {
  const map: Record<string, number | null> = {}
  const priceMap: Record<string, number | null> = {}
  item.timeline.forEach((minute, index) => {
    map[minute] = item.values[index] ?? null
    if (item.price_values) {
      priceMap[minute] = item.price_values[index] ?? null
    }
  })
  const values = boardTimeline.map((minute) => (minute in map ? map[minute]! : null))
  const price_values = item.price_values
    ? boardTimeline.map((minute) => (minute in priceMap ? priceMap[minute]! : null))
    : undefined
  return {
    id: item.id,
    name: item.name,
    symbol: item.symbol,
    sector_type: item.sector_type,
    cum_main: item.cum_main,
    change_pct: item.change_pct,
    values,
    price_values,
  }
}

async function resolveTradeDate(requested?: string | null): Promise<string> {
  const dates = await fetchReplayDates()
  if (requested && dates.dates.includes(requested)) return requested
  if (dates.dates.length > 0) return dates.dates[dates.dates.length - 1]!
  return new Date().toISOString().slice(0, 10)
}

function pickLatestMinute(
  minutesMeta?: Awaited<ReturnType<typeof fetchReplayMinutes>> | null,
  overview?: Awaited<ReturnType<typeof fetchMarketOverview>> | null,
  tradeDate?: string,
): string | null {
  const raw =
    minutesMeta?.latest_available_minute ??
    minutesMeta?.latest_sector_minute ??
    minutesMeta?.latest_stock_minute ??
    minutesMeta?.latest_complete_minute ??
    overview?.latest_available_minute ??
    overview?.latest_complete_minute ??
    null
  if (tradeDate) return capLiveReplayMinute(raw, tradeDate)
  return raw
}

async function resolveRankingMinute(
  tradeDate: string,
  replayMinute?: string | null,
  minutesMeta?: Awaited<ReturnType<typeof fetchReplayMinutes>> | null,
  overview?: Awaited<ReturnType<typeof fetchMarketOverview>> | null,
): Promise<string> {
  if (minutesMeta?.minutes.length) {
    const latest =
      pickLatestMinute(minutesMeta, overview, tradeDate) ?? minutesMeta.minutes[minutesMeta.minutes.length - 1]!
    if (replayMinute && minutesMeta.minutes.includes(replayMinute)) {
      return replayMinute
    }
    return latest
  }
  if (replayMinute) return replayMinute
  try {
    const minutesMetaFallback = await fetchReplayMinutes(tradeDate)
    const latest = pickLatestMinute(minutesMetaFallback, overview, tradeDate)
    if (latest) return latest
  } catch {
    /* optional */
  }
  try {
    const overviewFallback = overview ?? (await fetchMarketOverview(tradeDate))
    const latest = pickLatestMinute(null, overviewFallback, tradeDate)
    if (latest) return latest
  } catch {
    /* optional */
  }
  return '09:31'
}

async function loadAutoSectorBoards(
  sectorDate: string,
  autoSectorCount: number,
  rankingMinute: string,
): Promise<BoardItem[]> {
  const attempts: (string | undefined)[] = [rankingMinute, undefined]
  for (const minute of attempts) {
    try {
      const rank = await fetchSectorRank(sectorDate, minute, autoSectorCount)
      if (rank.items.length) {
        return rank.items.map((item) => toBoardItem(item))
      }
    } catch {
      /* try next strategy */
    }
  }

  const sectorsResponse = await fetchSectors()
  return pickDefaultBoards(sectorsResponse.items).slice(0, autoSectorCount)
}

function isWeekdayDate(dateStr: string): boolean {
  const day = new Date(`${dateStr}T12:00:00`).getDay()
  return day >= 1 && day <= 5
}

async function loadSectorBoards(
  sectorSourceMode: SectorSourceMode,
  sectorDate: string,
  autoSectorCount: number,
  rankingMinute: string,
): Promise<{ boards: BoardItem[]; sectorMode: string }> {
  if (sectorSourceMode === 'auto') {
    const boards = await loadAutoSectorBoards(sectorDate, autoSectorCount, rankingMinute)
    return { boards, sectorMode: 'auto' }
  }

  const sectorsResponse = await fetchSectors()
  let selectedBoards = enrichBoardItems(loadSelectedBoards(), sectorsResponse.items).filter((board) =>
    sectorsResponse.items.some((item) => item.sector_id === board.id),
  )
  if (!selectedBoards.length) {
    try {
      const targets = await fetchCollectionTargets()
      if (targets.sector_ids.length) {
        const byId = new Map(sectorsResponse.items.map((item) => [item.sector_id, item]))
        selectedBoards = targets.sector_ids
          .map((sectorId) => byId.get(sectorId))
          .filter((item): item is NonNullable<typeof item> => item != null)
          .map((item) => toBoardItem(item))
      }
    } catch {
      /* optional */
    }
  }
  if (!selectedBoards.length) {
    const boards = await loadAutoSectorBoards(sectorDate, autoSectorCount, rankingMinute)
    return { boards, sectorMode: 'auto-fallback' }
  }
  return { boards: selectedBoards, sectorMode: 'selected' }
}

type WorkbenchBoardOptions = {
  stockDate?: string | null
  sectorDate?: string | null
  sectorSourceMode?: SectorSourceMode
  stockSourceMode?: StockSourceMode
  linkageSectorId?: string | null
  linkageSectorName?: string | null
  autoSectorCount?: number
  linkageTopK?: number
  replayMinute?: string | null
}

type StockPanelBundle = {
  stockTargets: BoardItem[]
  stockMode: string
  stockSeries: FlowSeries[]
  stockTimeline: string[]
  watchlist: BoardPayload['watchlist']
}

async function loadStockTargets(
  stockSourceMode: StockSourceMode,
  stockDate: string,
  rankingMinute: string,
  linkageSectorId: string | null,
  linkageTopK: number,
  linkageSectorName?: string | null,
): Promise<{ stocks: BoardItem[]; stockMode: string }> {
  if (stockSourceMode === 'linkage' && linkageSectorId) {
    try {
      const members = await fetchSectorMembers(
        linkageSectorId,
        stockDate,
        rankingMinute,
        linkageTopK,
        linkageSectorName ?? undefined,
      )
      const stocks = members.items.map((item) => ({
        id: item.symbol,
        name: item.name,
        change_pct: item.change_pct,
        cum_main: item.main_cumulative,
      }))
      if (stocks.length) return { stocks, stockMode: 'linkage' }
    } catch {
      try {
        const catalog = await fetchSectorCatalogMembers(
          linkageSectorId,
          linkageSectorName ?? undefined,
        )
        const stocks = catalog.items.slice(0, linkageTopK).map((item) => ({
          id: item.symbol,
          name: item.name,
        }))
        if (stocks.length) return { stocks, stockMode: 'linkage' }
      } catch {
        /* fall through */
      }
    }
    return { stocks: [], stockMode: 'linkage' }
  }

  const selectedStocks = loadSelectedStocks()
  return {
    stocks: selectedStocks,
    stockMode: selectedStocks.length ? 'selected' : stockSourceMode === 'linkage' ? 'linkage' : 'empty',
  }
}

async function loadStockPanelBundle(
  opts: WorkbenchBoardOptions | undefined,
  rankingMinute: string,
  timelineFallback: string[],
): Promise<StockPanelBundle> {
  const stockSourceMode = opts?.stockSourceMode ?? loadStockSourceMode()
  const linkageTopK = opts?.linkageTopK ?? loadLinkageTopK()
  const linkageSectorId = opts?.linkageSectorId ?? null
  const stockDate = await resolveTradeDate(opts?.stockDate)

  const { stocks: stockTargets, stockMode } = await loadStockTargets(
    stockSourceMode,
    stockDate,
    rankingMinute,
    linkageSectorId,
    linkageTopK,
    opts?.linkageSectorName,
  )

  const useLiveMemberValues = stockSourceMode === 'linkage' && Boolean(linkageSectorId)

  const stockResults = await Promise.all(
    stockTargets.map(async (stock) => {
      try {
        const payload = await fetchStockFundFlow(stock.id, stockDate)
        let points = payload.points
        if (!points.some((point) => point.close != null && Number.isFinite(point.close))) {
          try {
            const intraday = await fetchStockIntraday(stock.id, stockDate)
            points = mergeIntradayPrices(points, intraday.points)
          } catch {
            /* optional fallback */
          }
        }
        let raw = buildRawSeries(stock.id, stock.name, points, stock.change_pct ?? null, {
          symbol: stock.id,
        })
        if (
          raw &&
          useLiveMemberValues &&
          stock.cum_main != null &&
          Number.isFinite(stock.cum_main) &&
          raw.values.filter((value) => value != null).length >= 2
        ) {
          raw = extendSeriesWithLivePoint(
            raw,
            rankingMinute,
            stock.cum_main,
            stock.change_pct ?? null,
          )
        }
        return raw ? { raw, stock } : null
      } catch {
        return null
      }
    }),
  )

  const rawStockSeries = stockResults
    .filter((item): item is NonNullable<typeof item> => item?.raw != null)
    .map((item) => item.raw)
  const stockTimeline = mergeTimeline(rawStockSeries).length
    ? mergeTimeline(rawStockSeries)
    : timelineFallback
  const stockSeries = rawStockSeries.map((item) => alignToTimeline(item, stockTimeline))

  return {
    stockTargets,
    stockMode,
    stockSeries,
    stockTimeline,
    watchlist: stockResults
      .filter((item): item is NonNullable<typeof item> => item != null)
      .map((item) => ({
        symbol: item.stock.id,
        name: item.stock.name,
        cum_main: item.raw.cum_main,
        quote: { change_pct: item.raw.change_pct },
      })),
  }
}

export async function fetchWorkbenchStockPanel(opts?: WorkbenchBoardOptions): Promise<
  Pick<
    BoardPayload,
    'stock_series' | 'stock_timeline' | 'watchlist' | 'stock_mode' | 'selected_stocks' | 'stock_view_date'
  >
> {
  const stockDate = await resolveTradeDate(opts?.stockDate)
  let minutesMeta: Awaited<ReturnType<typeof fetchReplayMinutes>> | null = null
  try {
    minutesMeta = await fetchReplayMinutes(stockDate)
  } catch {
    /* optional */
  }
  const rankingMinute = await resolveRankingMinute(stockDate, opts?.replayMinute, minutesMeta, null)
  const timelineFallback = minutesMeta?.minutes.length ? [...minutesMeta.minutes] : []
  const bundle = await loadStockPanelBundle(opts, rankingMinute, timelineFallback)

  return {
    stock_view_date: stockDate,
    stock_mode: bundle.stockMode,
    selected_stocks: (opts?.stockSourceMode ?? loadStockSourceMode()) === 'selected' ? bundle.stockTargets : [],
    watchlist: bundle.watchlist,
    stock_timeline: bundle.stockTimeline,
    stock_series: bundle.stockSeries,
  }
}

export async function fetchWorkbenchBoard(opts?: WorkbenchBoardOptions): Promise<BoardPayload> {
  const sectorSourceMode = opts?.sectorSourceMode ?? loadSectorSourceMode()
  const stockSourceMode = opts?.stockSourceMode ?? loadStockSourceMode()
  const autoSectorCount = opts?.autoSectorCount ?? loadAutoSectorCount()
  const linkageSectorId = opts?.linkageSectorId ?? null

  const sectorDate = await resolveTradeDate(opts?.sectorDate)
  const stockDate = await resolveTradeDate(opts?.stockDate ?? sectorDate)

  let sectorError: string | null = null
  let minutesMeta: Awaited<ReturnType<typeof fetchReplayMinutes>> | null = null
  let overview: Awaited<ReturnType<typeof fetchMarketOverview>> | null = null

  try {
    overview = await fetchMarketOverview(sectorDate)
  } catch {
    /* optional */
  }

  try {
    minutesMeta = await fetchReplayMinutes(sectorDate)
  } catch {
    if (!overview?.latest_available_minute) {
      sectorError = `暂无 ${sectorDate} 的分钟采样，请先在设置中确认采集数据或切换交易日`
    }
  }

  const rankingMinute = await resolveRankingMinute(sectorDate, opts?.replayMinute, minutesMeta, overview)

  const { boards: sectorBoards, sectorMode } = await loadSectorBoards(
    sectorSourceMode,
    sectorDate,
    autoSectorCount,
    rankingMinute,
  )

  if (sectorSourceMode === 'auto' && sectorBoards.length) {
    try {
      await syncWorkbenchPriorityTargets()
    } catch {
      /* keep board load resilient */
    }
  }

  const sectorResults = await Promise.all(
    sectorBoards.map(async (board) => {
      try {
        const payload = await fetchSectorFundFlow(board.id, sectorDate)
        return {
          board,
          series: buildRawSeries(board.id, board.name, payload.points, payload.change_pct ?? null, {
            sector_type: board.sector_type,
          }),
        }
      } catch {
        return { board, series: null }
      }
    }),
  )

  const missingSectorBoards = sectorResults
    .filter((item) => item.series == null)
    .map((item) => item.board)
  const rawSectorSeries = sectorResults
    .map((item) => item.series)
    .filter((item): item is RawSeries => item != null)
  const timeline = (() => {
    if (minutesMeta?.minutes.length) {
      const mins = filterLiveReplayMinutes([...minutesMeta.minutes], sectorDate)
      const first = mins[0]
      const prev = first ? previousTradingMinute(first) : null
      if (prev && !mins.includes(prev)) mins.unshift(prev)
      return mins
    }
    return mergeTimeline(rawSectorSeries)
  })()
  const sectorSeries = rawSectorSeries.map((item) => alignToTimeline(item, timeline))

  const stockBundle = await loadStockPanelBundle(opts, rankingMinute, timeline)
  const { stockTargets, stockMode, stockSeries, stockTimeline } = stockBundle

  const latestMinute = pickLatestMinute(minutesMeta, overview, sectorDate) ?? rankingMinute
  const hasSectorData = sectorSeries.length > 0
  const hasLiveMinute = Boolean(
    overview?.latest_available_minute ??
      minutesMeta?.latest_available_minute ??
      (minutesMeta?.minutes.length ? minutesMeta.minutes[minutesMeta.minutes.length - 1] : null),
  )
  const hasSessionData = hasLiveMinute || hasSectorData
  const today = new Date().toISOString().slice(0, 10)
  const isToday = sectorDate === today
  const marketStatus = (() => {
    if (!hasSessionData) {
      if (isToday && isWeekdayDate(sectorDate)) return 'pre_open'
      return 'non_trading_day'
    }
    if (hasSectorData) return isToday ? 'open' : 'closed'
    return isToday ? 'open' : 'pre_open'
  })()

  if (!hasSectorData && !sectorError) {
    if (sectorSourceMode === 'auto' && sectorBoards.length) {
      sectorError = `${sectorDate} 暂无 ${sectorBoards.length} 个板块的分时曲线数据`
    } else if (sectorSourceMode === 'auto') {
      sectorError = `${sectorDate} 暂无主力流入榜数据（前 ${autoSectorCount} 板块）`
    } else if (sectorBoards.length) {
      sectorError = `已选 ${sectorBoards.length} 个板块，但 ${sectorDate} 暂无资金曲线数据`
    }
  }

  let stockHint: string | undefined
  if (stockSourceMode === 'linkage' && !linkageSectorId) {
    stockHint = '点击左侧板块查看成分股主力'
  } else if (stockSourceMode === 'linkage' && linkageSectorId && !stockSeries.length) {
    stockHint = '该板块暂无成分股采样数据'
  } else if (stockSourceMode === 'selected' && !stockTargets.length) {
    stockHint = '尚未添加自选个股，请点击「管理自选」添加'
  }

  const sectorHint =
    sectorSourceMode === 'selected' && !sectorBoards.length
      ? '尚未添加自选板块，请点击「管理自选」添加'
      : missingSectorBoards.length
        ? `${missingSectorBoards.length} 个板块暂无 ${sectorDate} 曲线：${missingSectorBoards
            .slice(0, 3)
            .map((b) => b.name)
            .join('、')}${missingSectorBoards.length > 3 ? '…' : ''}（需等待采集器补采）`
        : undefined

  return {
    updated_at: new Date().toISOString(),
    error: sectorError,
    disclaimer: '板块/个股主力来自 Workbench 采集聚合；分时数据依赖分钟采样批次。',
    host: 'workbench',
    board_type: 'GN',
    sector_mode: sectorMode,
    selected_boards: sectorSourceMode === 'selected' ? sectorBoards : [],
    stock_mode: stockMode,
    selected_stocks: stockSourceMode === 'selected' ? stockTargets : [],
    watchlist: stockBundle.watchlist,
    timeline,
    sector_series: sectorSeries,
    stock_timeline: stockTimeline,
    stock_series: stockSeries,
    stock_view_date: stockDate,
    sector_view_date: sectorDate,
    stock_intraday_dates: (await fetchReplayDates()).dates,
    sector_intraday_dates: (await fetchReplayDates()).dates,
    intraday_retention_days: 30,
    trading_session: {
      tradeDate: sectorDate,
      currentMinute: latestMinute ?? rankingMinute,
      marketStatus,
      sessionStatus: hasSectorData ? (isToday ? 'open' : 'closed') : hasSessionData ? 'open' : 'idle',
      isTradingDay: hasSessionData || (isToday && isWeekdayDate(sectorDate)),
      message:
        sectorError ??
        sectorHint ??
        stockHint ??
        (hasSectorData
          ? `数据截至 ${latestMinute ?? rankingMinute}`
          : hasLiveMinute
            ? `采集进行中，最新 ${latestMinute ?? rankingMinute}`
            : undefined),
    },
  }
}

export async function fetchWorkbenchBoardCatalog(
  type: BoardCatalogType,
  q = '',
  limit = 300,
): Promise<CatalogResponse> {
  const response = await fetchSectors()
  const filterType = BOARD_TYPE_FILTER[type]
  const rawQuery = q.trim()
  const query = rawQuery.toLowerCase()
  const isCodeQuery = /^\d{6}$/.test(rawQuery)
  const isClassicQuery = isClassicIndexCodeQuery(rawQuery)
  let items = response.items
  if (isClassicQuery) {
    items = items.filter((item) => item.sector_type === 'classic_index')
  } else if (filterType && !isCodeQuery) {
    items = items.filter((item) => item.sector_type === filterType)
  }
  let boards = items.map((item) => toBoardItem(item))
  if (query) {
    boards = boards.filter(
      (board) => board.name.toLowerCase().includes(query) || board.id.includes(query),
    )
  }
  const searchHint = query && !boards.length ? legacySectorSearchHint(q.trim(), type) : null
  return { boards: boards.slice(0, limit), type, searchHint: searchHint ?? undefined }
}

export async function fetchWorkbenchSelectedBoards(): Promise<SelectedBoardsResponse> {
  const boards = loadSelectedBoards()
  return { boards }
}

export async function syncLinkageSector(
  sectorId: string | null,
  sectorName?: string | null,
): Promise<void> {
  try {
    await fetch('/api/v1/settings/linkage-sector', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sector_id: sectorId ?? '',
        sector_name: sectorName ?? '',
      }),
    })
    await syncWorkbenchPriorityTargets({
      linkageSectorId: sectorId,
      linkageSectorName: sectorName,
    })
  } catch {
    /* 联动板块同步失败不阻塞 UI */
  }
}

export async function syncWorkbenchPriorityTargets(opts?: {
  linkageSectorId?: string | null
  linkageSectorName?: string | null
}): Promise<void> {
  const selectedBoards = loadSelectedBoards()
  const selectedStocks = loadSelectedStocks()
  const autoCount = loadAutoSectorCount()
  let rankSectorIds: string[] = []
  try {
    const sectorDate = await resolveTradeDate(null)
    const rank = await fetchSectorRank(sectorDate, undefined, autoCount)
    rankSectorIds = rank.items.map((item) => item.sector_id)
  } catch {
    /* rank optional */
  }
  try {
    await fetch('/api/v1/settings/sync-hot-targets', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_sector_ids: selectedBoards.map((b) => b.id),
        rank_sector_ids: rankSectorIds,
        symbols: selectedStocks.map((s) => s.id),
        linkage_sector_id: opts?.linkageSectorId ?? '',
        linkage_sector_name: opts?.linkageSectorName ?? '',
      }),
    })
  } catch {
    /* 启动时同步失败不阻塞 */
  }
}

export async function syncWorkbenchPrioritySectors(): Promise<void> {
  await syncWorkbenchPriorityTargets()
}

export async function saveWorkbenchSelectedBoards(boards: BoardItem[]): Promise<void> {
  saveSelectedBoardsLocal(boards)
  await syncWorkbenchPriorityTargets()
}

export async function fetchWorkbenchStockCatalog(q = '', limit = 50): Promise<StockCatalogResponse> {
  if (!q.trim()) return { stocks: [], total: 0 }
  const response = await searchSecurities(q.trim())
  const stocks = response.results.slice(0, limit).map((item) => ({
    id: item.symbol,
    name: item.name,
  }))
  return { stocks, total: stocks.length }
}

export async function fetchWorkbenchSelectedStocks(): Promise<SelectedStocksResponse> {
  return { stocks: loadSelectedStocks() }
}

export async function saveWorkbenchSelectedStocks(stocks: BoardItem[]): Promise<void> {
  saveSelectedStocksLocal(stocks)
  await syncWorkbenchPriorityTargets()
}

export async function fetchWorkbenchStock(symbol: string, date?: string | null): Promise<StockDetail | null> {
  const tradeDate = await resolveTradeDate(date)
  try {
    const payload = await fetchStockFundFlow(symbol, tradeDate)
    const fundFlow = payload.points.map((point) => ({
      time: point.minute,
      cum_main: point.values.main?.cumulative ?? null,
      cum_net: point.values.main?.cumulative ?? null,
      change_pct: null,
      price: null,
    }))
    return {
      symbol: symbol.toUpperCase(),
      trade_date: tradeDate,
      fund_flow: fundFlow,
      quote: {
        change_pct: null,
        price: null,
      },
    }
  } catch {
    return null
  }
}

export async function refreshWorkbenchBoardData(): Promise<void> {
  /* workbench 只读查询，刷新由前端重新拉取 board 完成 */
}
