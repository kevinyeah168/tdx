import { fetchCustomSectors } from '@/api/customSectors'
import { fetchMarketOverview, searchSecurities } from '@/api/market'
import { fetchReplayDates, fetchReplayMinutes } from '@/api/replay'
import {
  addSectorGroupMembers,
  createSectorGroup,
  fetchSectorGroups,
  MAX_GROUP_MEMBERS,
  setActiveSectorGroup,
  setSectorGroupMemberChartVisible,
} from '@/api/sectorGroups'
import {
  fetchSectorCatalogMembers,
  fetchSectorFundFlowBatch,
  fetchSectorGrayFlowBatch,
  fetchSectorMembers,
  fetchSectorSnapshot,
  fetchSectors,
  type CurvePoint,
  type SectorGrayFlowPoint,
} from '@/api/sectors'
import {
  fetchStockFundFlow,
  fetchStockFundFlowBatch,
  fetchStockGrayFlowBatch,
  type StockGrayFlowPoint,
} from '@/api/stocks'
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
import {
  isWeekdayDate,
  resolveLiveMarketStatus,
  shouldFetchMarketDataForDate,
} from '@/utils/tradingSession'
import { todayTradeDate } from '@/utils/tradeDate'
import { computeAvgPriceValues } from '@/utils/avgPrice'
import { legacySectorSearchHint, isClassicIndexCodeQuery } from '@/utils/sectorCodeAliases'
import { inferSectorTypeFromId, resolveSectorType } from '@/utils/format'

const SELECTED_BOARDS_KEY = 'workbench-selected-boards'
const SECTOR_GROUP_MIGRATED_KEY = 'workbench-sector-group-migrated'
const SELECTED_STOCKS_KEY = 'workbench-selected-stocks'
const SECTOR_SOURCE_MODE_KEY = 'workbench-sector-source-mode'
const STOCK_SOURCE_MODE_KEY = 'workbench-stock-source-mode'
const AUTO_SECTOR_COUNT_KEY = 'workbench-auto-sector-count'
const LINKAGE_TOP_K_KEY = 'workbench-linkage-top-k'

export type SectorSourceMode = 'auto' | 'selected'
export type StockSourceMode = 'linkage' | 'selected'

export const DEFAULT_AUTO_SECTOR_COUNT = 60
export const DEFAULT_LINKAGE_TOP_K = 60
export const MAX_CHART_SECTORS = 60

const BOARD_TYPE_FILTER: Partial<Record<BoardCatalogType, string>> = {
  HY: 'industry',
  GN: 'concept',
  HY2: 'industry2',
  IDX: 'classic_index',
  CUSTOM: 'custom',
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
  if (typeof value === 'number' && value >= 4 && value <= 60) return value
  return DEFAULT_AUTO_SECTOR_COUNT
}

export function saveAutoSectorCount(count: number) {
  writeStorage(AUTO_SECTOR_COUNT_KEY, count)
}

export function loadLinkageTopK(): number {
  const value = readStorage<number>(LINKAGE_TOP_K_KEY)
  if (typeof value === 'number' && value >= 5 && value <= 60) return value
  return DEFAULT_LINKAGE_TOP_K
}

export function saveLinkageTopK(topK: number) {
  writeStorage(LINKAGE_TOP_K_KEY, topK)
}

export function loadSelectedBoards(): BoardItem[] {
  return normalizeChartVisibility(readStorage<BoardItem[]>(SELECTED_BOARDS_KEY) ?? [])
}

export function saveSelectedBoardsLocal(boards: BoardItem[]) {
  writeStorage(SELECTED_BOARDS_KEY, normalizeChartVisibility(boards))
}

export function normalizeChartVisibility(boards: BoardItem[]): BoardItem[] {
  if (!boards.length) return []
  const anyExplicit = boards.some(
    (board) => board.chart_visible === true || board.chart_visible === false,
  )
  if (!anyExplicit) {
    return boards.map((board, index) => ({
      ...board,
      chart_visible: index < MAX_CHART_SECTORS,
    }))
  }
  let visibleKept = 0
  const normalized = boards.map((board) => {
    if (!board.chart_visible) {
      return { ...board, chart_visible: false }
    }
    visibleKept += 1
    if (visibleKept > MAX_CHART_SECTORS) {
      return { ...board, chart_visible: false }
    }
    return { ...board, chart_visible: true }
  })
  if (!normalized.some((board) => board.chart_visible)) {
    return boards.map((board, index) => ({
      ...board,
      chart_visible: index < MAX_CHART_SECTORS,
    }))
  }
  return normalized
}

export function boardsForChart(boards: BoardItem[]): BoardItem[] {
  return normalizeChartVisibility(boards)
    .filter((board) => board.chart_visible)
    .slice(0, MAX_CHART_SECTORS)
}

export function chartVisibleCount(boards: BoardItem[]): number {
  return boardsForChart(boards).length
}

export function loadSelectedStocks(): BoardItem[] {
  return readStorage<BoardItem[]>(SELECTED_STOCKS_KEY) ?? []
}

export function saveSelectedStocksLocal(stocks: BoardItem[]) {
  writeStorage(SELECTED_STOCKS_KEY, stocks)
}

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

interface RawSeries {
  id: string
  name: string
  symbol?: string
  sector_type?: string | null
  cum_main: number
  change_pct: number | null
  main_net_ratio?: number | null
  free_float_market_cap?: number | null
  main_net_ratio_avg?: number | null
  free_float_market_cap_avg?: number | null
  timeline: string[]
  values: (number | null)[]
  price_values?: (number | null)[]
  avg_price_values?: (number | null)[]
}

function computeMainNetRatio(
  mainCum: number | null | undefined,
  freeFloatMarketCap: number | null | undefined,
): number | null {
  if (
    mainCum == null ||
    freeFloatMarketCap == null ||
    !Number.isFinite(mainCum) ||
    !Number.isFinite(freeFloatMarketCap) ||
    freeFloatMarketCap <= 0
  ) {
    return null
  }
  return Math.round((mainCum / freeFloatMarketCap) * 100 * 10000) / 10000
}

function computeIndexPriceValues(
  changePcts: (number | null)[],
  preClose: number | null | undefined,
): (number | null)[] {
  if (preClose == null || preClose <= 0) return changePcts.map(() => null)
  return changePcts.map((pct) =>
    pct == null || !Number.isFinite(pct) ? null : preClose * (1 + pct / 100),
  )
}

function buildRawSeries(
  id: string,
  name: string,
  points: CurvePoint[],
  changePct: number | null,
  extra?: {
    symbol?: string
    sector_type?: string | null
    main_net_ratio?: number | null
    free_float_market_cap?: number | null
    main_net_ratio_avg?: number | null
    free_float_market_cap_avg?: number | null
    pre_close?: number | null
    trade_date?: string | null
  },
): RawSeries | null {
  const livePoints = withoutPrematureClosingPoint(points, extra?.trade_date)
  if (!livePoints.length) return null

  let timeline = livePoints.map((point) => point.minute)
  let values = livePoints.map((point) => point.values.main?.cumulative ?? null)
  let price_values = livePoints.map((point) =>
    point.close != null && Number.isFinite(point.close) ? point.close : null,
  )
  const change_pcts = livePoints.map((point) =>
    point.change_pct != null && Number.isFinite(point.change_pct) ? point.change_pct : null,
  )
  const amount_deltas = livePoints.map((point) =>
    point.amount_delta != null && Number.isFinite(point.amount_delta) ? point.amount_delta : null,
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
  const hasStockClose = price_values.some((v) => v != null)
  const hasSectorIndex = !hasStockClose && change_pcts.some((v) => v != null) && extra?.pre_close
  let avg_price_values: (number | null)[] | undefined
  if (hasStockClose) {
    const avg = computeAvgPriceValues(price_values, amount_deltas)
    if (avg.some((v) => v != null)) avg_price_values = avg
  } else if (hasSectorIndex) {
    price_values = computeIndexPriceValues(change_pcts, extra.pre_close)
  }

  const hasPrice = price_values.some((v) => v != null)
  const cumMain = last.values.main?.cumulative ?? 0
  const freeCap = extra?.free_float_market_cap ?? null
  const freeCapAvg = extra?.free_float_market_cap_avg ?? null
  const ratio =
    computeMainNetRatio(cumMain, freeCap) ?? extra?.main_net_ratio ?? null
  const ratioAvg =
    computeMainNetRatio(cumMain, freeCapAvg) ?? extra?.main_net_ratio_avg ?? null
  return {
    id,
    name,
    symbol: extra?.symbol,
    sector_type: extra?.sector_type ?? inferSectorTypeFromId(id),
    cum_main: cumMain,
    change_pct: changePct,
    main_net_ratio: ratio,
    free_float_market_cap: freeCap,
    main_net_ratio_avg: ratioAvg,
    free_float_market_cap_avg: freeCapAvg,
    timeline,
    values,
    price_values: hasPrice ? price_values : undefined,
    avg_price_values,
  }
}

function extendSeriesWithLivePoint(
  series: RawSeries,
  minute: string,
  liveMain: number,
  changePct: number | null,
): RawSeries {
  const ratio =
    computeMainNetRatio(liveMain, series.free_float_market_cap) ?? series.main_net_ratio ?? null
  const ratioAvg =
    computeMainNetRatio(liveMain, series.free_float_market_cap_avg) ??
    series.main_net_ratio_avg ??
    null
  const lastIndex = series.timeline.length - 1
  const lastMinute = lastIndex >= 0 ? series.timeline[lastIndex] : null
  if (lastMinute === minute) {
    const values = [...series.values]
    values[lastIndex] = liveMain
    return {
      ...series,
      cum_main: liveMain,
      change_pct: changePct ?? series.change_pct,
      main_net_ratio: ratio,
      main_net_ratio_avg: ratioAvg,
      values,
    }
  }
  if (lastMinute && minute > lastMinute) {
    return {
      ...series,
      cum_main: liveMain,
      change_pct: changePct ?? series.change_pct,
      main_net_ratio: ratio,
      main_net_ratio_avg: ratioAvg,
      timeline: [...series.timeline, minute],
      values: [...series.values, liveMain],
    }
  }
  return {
    ...series,
    cum_main: liveMain,
    change_pct: changePct ?? series.change_pct,
    main_net_ratio: ratio,
    main_net_ratio_avg: ratioAvg,
  }
}

function mergeTimeline(items: RawSeries[]): string[] {
  const minutes = new Set<string>()
  for (const item of items) {
    for (const minute of item.timeline) minutes.add(minute)
  }
  return [...minutes].sort()
}

function attachGrayToFlowSeries(
  series: FlowSeries,
  grayPoints: Array<StockGrayFlowPoint | SectorGrayFlowPoint>,
  boardTimeline: string[],
): FlowSeries {
  if (!grayPoints.length) return series
  const map = new Map(grayPoints.map((point) => [point.minute, point.dark_cumulative]))
  let last: number | null = null
  const gray_values = boardTimeline.map((minute) => {
    if (map.has(minute)) last = map.get(minute)!
    return last
  })
  const lastPoint = grayPoints[grayPoints.length - 1]
  return {
    ...series,
    gray_values,
    cum_gray: lastPoint?.dark_cumulative ?? null,
  }
}

function alignToTimeline(item: RawSeries, boardTimeline: string[]): FlowSeries {
  const map: Record<string, number | null> = {}
  const priceMap: Record<string, number | null> = {}
  const avgMap: Record<string, number | null> = {}
  item.timeline.forEach((minute, index) => {
    map[minute] = item.values[index] ?? null
    if (item.price_values) {
      priceMap[minute] = item.price_values[index] ?? null
    }
    if (item.avg_price_values) {
      avgMap[minute] = item.avg_price_values[index] ?? null
    }
  })
  const values = boardTimeline.map((minute) => (minute in map ? map[minute]! : null))
  const price_values = item.price_values
    ? boardTimeline.map((minute) => (minute in priceMap ? priceMap[minute]! : null))
    : undefined
  const avg_price_values = item.avg_price_values
    ? boardTimeline.map((minute) => (minute in avgMap ? avgMap[minute]! : null))
    : undefined
  return {
    id: item.id,
    name: item.name,
    symbol: item.symbol,
    sector_type: item.sector_type,
    cum_main: item.cum_main,
    change_pct: item.change_pct,
    main_net_ratio: item.main_net_ratio ?? null,
    free_float_market_cap: item.free_float_market_cap ?? null,
    main_net_ratio_avg: item.main_net_ratio_avg ?? null,
    free_float_market_cap_avg: item.free_float_market_cap_avg ?? null,
    values,
    price_values,
    avg_price_values,
  }
}

async function resolveTradeDate(requested?: string | null): Promise<string> {
  // Explicit panel/TopBar picks must stick — never silently jump to the latest date.
  if (requested && /^\d{4}-\d{2}-\d{2}$/.test(requested)) {
    return requested
  }
  try {
    const dates = await fetchReplayDates()
    if (dates.dates.length > 0) return dates.dates[dates.dates.length - 1]!
  } catch {
    /* fall through */
  }
  return todayTradeDate()
}

function hasIntradaySamples(
  minutesMeta: Awaited<ReturnType<typeof fetchReplayMinutes>> | null | undefined,
  overview: Awaited<ReturnType<typeof fetchMarketOverview>> | null | undefined,
): boolean {
  if (minutesMeta?.minutes?.length) return true
  if (
    minutesMeta?.latest_available_minute ||
    minutesMeta?.latest_complete_minute ||
    minutesMeta?.latest_sector_minute ||
    minutesMeta?.latest_stock_minute
  ) {
    return true
  }
  if (overview?.latest_available_minute || overview?.latest_complete_minute) return true
  return false
}

function shouldFetchCurves(
  tradeDate: string,
  replayDates: string[],
  minutesMeta: Awaited<ReturnType<typeof fetchReplayMinutes>> | null | undefined,
  overview: Awaited<ReturnType<typeof fetchMarketOverview>> | null | undefined,
  calendarToday = todayTradeDate(),
): boolean {
  if (replayDates.includes(tradeDate)) return true
  if (hasIntradaySamples(minutesMeta, overview)) return true
  if (tradeDate === calendarToday && isWeekdayDate(tradeDate)) return true
  return false
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
  if (!shouldFetchMarketDataForDate(tradeDate)) {
    return replayMinute ?? '09:31'
  }
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

async function migrateLegacyWatchlistToGroups(): Promise<void> {
  try {
    if (localStorage.getItem(SECTOR_GROUP_MIGRATED_KEY)) return
    const legacy = loadSelectedBoards()
    if (!legacy.length) {
      localStorage.setItem(SECTOR_GROUP_MIGRATED_KEY, '1')
      return
    }
    const existing = await fetchSectorGroups()
    if (!existing.items.length) {
      const group = await createSectorGroup('默认分组')
      const members = legacy.slice(0, MAX_GROUP_MEMBERS)
      if (members.length) {
        await addSectorGroupMembers(group.id, members.map((item) => item.id))
        for (const member of members) {
          if (member.chart_visible === false) {
            await setSectorGroupMemberChartVisible(group.id, member.id, false)
          }
        }
      }
      await setActiveSectorGroup(group.id)
    }
    saveSelectedBoardsLocal([])
    localStorage.setItem(SECTOR_GROUP_MIGRATED_KEY, '1')
  } catch {
    /* retry on next board load */
  }
}

async function loadSectorBoards(
  _sectorSourceMode: SectorSourceMode,
  _sectorDate: string,
  _autoSectorCount: number,
  _rankingMinute: string,
): Promise<{
  boards: BoardItem[]
  sectorMode: string
  selectedBoards: BoardItem[]
  activeGroupId: string | null
  activeGroupName: string | null
}> {
  await migrateLegacyWatchlistToGroups()
  const [groupsResponse, sectorsResponse] = await Promise.all([
    fetchSectorGroups(),
    fetchSectors(),
  ])
  const groups = groupsResponse.items
  let activeId = groupsResponse.active_group_id
  if (!groups.length) {
    return {
      boards: [],
      sectorMode: 'group',
      selectedBoards: [],
      activeGroupId: null,
      activeGroupName: null,
    }
  }
  if (activeId === 'all' || !groups.some((group) => group.id === activeId)) {
    const fallbackId = groups[0]!.id
    if (fallbackId) {
      activeId = fallbackId
      try {
        await setActiveSectorGroup(fallbackId)
      } catch {
        /* optional */
      }
    }
  }
  const group = groups.find((entry) => entry.id === activeId) ?? groups[0]!
  const selectedBoards = normalizeChartVisibility(
    enrichBoardItems(
      group.sectors.map((member) => ({
        id: member.sector_id,
        name: member.name,
        chart_visible: member.chart_visible ?? true,
      })),
      sectorsResponse.items,
    ),
  )
  const chartBoards = boardsForChart(selectedBoards)
  return {
    boards: chartBoards,
    sectorMode: 'group',
    selectedBoards,
    activeGroupId: group.id,
    activeGroupName: group.name,
  }
}

async function loadImportedCustomSectorBoards(): Promise<BoardItem[]> {
  try {
    const { items } = await fetchCustomSectors()
    return items
      .filter((item) => item.source_type === 'directory')
      .map((item) => ({
        id: item.sector_id,
        name: item.name,
        sector_type: 'custom',
        chart_visible: true,
      }))
  } catch {
    return []
  }
}

async function enrichSelectedBoardsWithSnapshot(
  boards: BoardItem[],
  tradeDate: string,
  minute: string,
): Promise<BoardItem[]> {
  if (!boards.length) return boards
  try {
    const snapshot = await fetchSectorSnapshot(
      boards.map((board) => board.id),
      tradeDate,
      minute,
    )
    const byId = new Map(snapshot.items.map((item) => [item.sector_id, item]))
    return boards.map((board) => {
      const hit = byId.get(board.id)
      if (!hit) return board
      return {
        ...board,
        cum_main: hit.main_cumulative,
        change_pct: hit.change_pct,
      }
    })
  } catch {
    return boards
  }
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

async function loadLinkageCatalogStocks(
  linkageSectorId: string,
  linkageTopK: number,
  linkageSectorName?: string | null,
): Promise<BoardItem[]> {
  try {
    const catalog = await fetchSectorCatalogMembers(
      linkageSectorId,
      linkageSectorName ?? undefined,
    )
    return catalog.items.slice(0, linkageTopK).map((item) => ({
      id: item.symbol,
      name: item.name,
    }))
  } catch {
    return []
  }
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
        main_net_ratio: item.main_net_ratio ?? null,
        free_float_market_cap: item.free_float_market_cap ?? null,
        main_net_ratio_avg: item.main_net_ratio_avg ?? null,
        free_float_market_cap_avg: item.free_float_market_cap_avg ?? null,
      }))
      if (stocks.length) return { stocks, stockMode: 'linkage' }
    } catch {
      /* fall through to catalog */
    }
    const catalogStocks = await loadLinkageCatalogStocks(
      linkageSectorId,
      linkageTopK,
      linkageSectorName,
    )
    if (catalogStocks.length) return { stocks: catalogStocks, stockMode: 'linkage' }
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
  fetchCurves = true,
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

  if (!fetchCurves || !stockTargets.length) {
    return {
      stockTargets,
      stockMode,
      stockSeries: [],
      stockTimeline: timelineFallback,
      watchlist: stockTargets.map((stock) => ({
        symbol: stock.id,
        name: stock.name,
        cum_main: stock.cum_main ?? null,
        quote: { change_pct: stock.change_pct ?? null },
      })),
    }
  }

  const symbols = stockTargets.map((stock) => stock.id)
  const [fundBatch, grayBatch] = await Promise.all([
    fetchStockFundFlowBatch(symbols, stockDate),
    fetchStockGrayFlowBatch(symbols, stockDate),
  ])
  const fundBySymbol = new Map(fundBatch.items.map((item) => [item.symbol.toUpperCase(), item]))
  const grayBySymbol = new Map(
    grayBatch.items.map((item) => [item.symbol.toUpperCase(), item.points]),
  )

  const stockResults = stockTargets.map((stock) => {
    try {
      const payload = fundBySymbol.get(stock.id.toUpperCase())
      if (!payload) return null
      let points = payload.points
      if (!points.some((point) => point.close != null && Number.isFinite(point.close))) {
        /* skip per-stock intraday fallback in batch mode to avoid N requests */
      }
      let raw = buildRawSeries(stock.id, stock.name, points, stock.change_pct ?? null, {
        symbol: stock.id,
        main_net_ratio: stock.main_net_ratio ?? null,
        free_float_market_cap: stock.free_float_market_cap ?? null,
        main_net_ratio_avg: stock.main_net_ratio_avg ?? null,
        free_float_market_cap_avg: stock.free_float_market_cap_avg ?? null,
        trade_date: stockDate,
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
      const grayPoints = grayBySymbol.get(stock.id.toUpperCase()) ?? null
      return raw
        ? { raw, stock, grayPoints: grayPoints?.length ? grayPoints : null }
        : null
    } catch {
      return null
    }
  })

  const validStockResults = stockResults.filter(
    (item): item is NonNullable<typeof item> => item?.raw != null,
  )
  const rawStockSeries = validStockResults.map((item) => item.raw)
  const stockTimeline = mergeTimeline(rawStockSeries).length
    ? mergeTimeline(rawStockSeries)
    : timelineFallback
  const stockSeries = validStockResults.map((item) => {
    const aligned = alignToTimeline(item.raw, stockTimeline)
    return item.grayPoints?.length
      ? attachGrayToFlowSeries(aligned, item.grayPoints, stockTimeline)
      : aligned
  })

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
  let replayDates: string[] = []
  try {
    replayDates = (await fetchReplayDates()).dates
  } catch {
    replayDates = []
  }
  let minutesMeta: Awaited<ReturnType<typeof fetchReplayMinutes>> | null = null
  if (shouldFetchMarketDataForDate(stockDate)) {
    try {
      minutesMeta = await fetchReplayMinutes(stockDate)
    } catch {
      /* optional */
    }
  }
  const rankingMinute = await resolveRankingMinute(stockDate, opts?.replayMinute, minutesMeta, null)
  const timelineFallback = minutesMeta?.minutes.length ? [...minutesMeta.minutes] : []
  const fetchCurves = shouldFetchCurves(stockDate, replayDates, minutesMeta, null)
  const bundle = await loadStockPanelBundle(opts, rankingMinute, timelineFallback, fetchCurves)

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

  let replayDates: string[] = []
  try {
    replayDates = (await fetchReplayDates()).dates
  } catch {
    replayDates = []
  }

  let sectorError: string | null = null
  let minutesMeta: Awaited<ReturnType<typeof fetchReplayMinutes>> | null = null
  let overview: Awaited<ReturnType<typeof fetchMarketOverview>> | null = null

  if (shouldFetchMarketDataForDate(sectorDate)) {
    try {
      overview = await fetchMarketOverview(sectorDate)
    } catch {
      /* optional */
    }

    try {
      minutesMeta = await fetchReplayMinutes(sectorDate)
    } catch {
      /* optional */
    }
  }

  const fetchCurves = shouldFetchCurves(sectorDate, replayDates, minutesMeta, overview)
  if (!shouldFetchMarketDataForDate(sectorDate)) {
    sectorError = `${sectorDate} 为非交易日，请切换至工作日查看`
  } else if (!fetchCurves && !hasIntradaySamples(minutesMeta, overview)) {
    sectorError = `暂无 ${sectorDate} 的分钟采样，请先在设置中确认采集数据或切换交易日`
  }

  const rankingMinute = await resolveRankingMinute(sectorDate, opts?.replayMinute, minutesMeta, overview)

  const {
    boards: groupChartBoards,
    sectorMode,
    selectedBoards: allSelectedBoards,
    activeGroupId,
    activeGroupName,
  } = await loadSectorBoards(sectorSourceMode, sectorDate, autoSectorCount, rankingMinute)
  const importedRaw = await loadImportedCustomSectorBoards()
  const importedIdSet = new Set(importedRaw.map((board) => board.id))
  const enrichedImportedBoards = importedRaw.length
    ? await enrichSelectedBoardsWithSnapshot(importedRaw, sectorDate, rankingMinute)
    : []
  const enrichedSelectedBoards = allSelectedBoards.length
    ? await enrichSelectedBoardsWithSnapshot(allSelectedBoards, sectorDate, rankingMinute)
    : allSelectedBoards
  const importedChartBoards = boardsForChart(enrichedImportedBoards)
  const sectorBoards = [...importedChartBoards, ...groupChartBoards.filter((board) => !importedIdSet.has(board.id))].slice(
    0,
    MAX_CHART_SECTORS,
  )

  let sectorResults: Array<{ board: BoardItem; series: RawSeries | null; grayPoints: SectorGrayFlowPoint[] | null }>
  if (!fetchCurves || !sectorBoards.length) {
    sectorResults = sectorBoards.map((board) => ({ board, series: null, grayPoints: null }))
  } else {
    const sectorIds = sectorBoards.map((board) => board.id)
    const [batch, grayBatch] = await Promise.all([
      fetchSectorFundFlowBatch(sectorIds, sectorDate),
      fetchSectorGrayFlowBatch(sectorIds, sectorDate).catch(() => ({
        trade_date: sectorDate,
        items: [],
      })),
    ])
    const payloadById = new Map(batch.items.map((item) => [item.sector_id, item]))
    const grayById = new Map(grayBatch.items.map((item) => [item.sector_id, item.points]))
    sectorResults = sectorBoards.map((board) => {
      const payload = payloadById.get(board.id)
      if (!payload) return { board, series: null, grayPoints: null }
      const grayPoints = grayById.get(board.id) ?? null
      return {
        board,
        series: buildRawSeries(board.id, board.name, payload.points, payload.change_pct ?? null, {
          sector_type: board.sector_type,
          pre_close: payload.pre_close ?? null,
          trade_date: sectorDate,
        }),
        grayPoints: grayPoints?.length ? grayPoints : null,
      }
    })
  }

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
  const snapshotBySectorId = new Map(
    [...enrichedImportedBoards, ...enrichedSelectedBoards].map((board) => [board.id, board.cum_main ?? null]),
  )
  const sectorSeries = sectorResults
    .filter((item): item is typeof item & { series: RawSeries } => item.series != null)
    .map((item) => {
      const aligned = alignToTimeline(item.series, timeline)
      const snapMain = snapshotBySectorId.get(aligned.id)
      const withMain =
        snapMain != null && Number.isFinite(snapMain)
          ? { ...aligned, cum_main: snapMain }
          : aligned
      return item.grayPoints?.length
        ? attachGrayToFlowSeries(withMain, item.grayPoints, timeline)
        : withMain
    })

  const seriesBySectorId = new Map(sectorSeries.map((item) => [item.id, item]))
  const attachSeriesMetrics = (board: BoardItem): BoardItem => {
    const series = seriesBySectorId.get(board.id)
    if (!series) return board
    return {
      ...board,
      cum_main: series.cum_main,
      cum_gray: series.cum_gray ?? null,
      change_pct: series.change_pct ?? board.change_pct ?? null,
    }
  }
  const finalImportedBoards = enrichedImportedBoards.map(attachSeriesMetrics)
  const finalSelectedBoards = enrichedSelectedBoards.map(attachSeriesMetrics)

  const stockBundle = await loadStockPanelBundle(opts, rankingMinute, timeline, fetchCurves)
  const { stockTargets, stockMode, stockSeries, stockTimeline } = stockBundle

  const latestMinute = pickLatestMinute(minutesMeta, overview, sectorDate) ?? rankingMinute
  const hasSectorData = sectorSeries.length > 0
  const hasLiveMinute = Boolean(
    overview?.latest_available_minute ??
      minutesMeta?.latest_available_minute ??
      (minutesMeta?.minutes.length ? minutesMeta.minutes[minutesMeta.minutes.length - 1] : null),
  )
  const calendarToday = todayTradeDate()
  const isToday = sectorDate === calendarToday
  const marketStatus = isToday
    ? resolveLiveMarketStatus(sectorDate, calendarToday)
    : isWeekdayDate(sectorDate)
      ? 'closed'
      : 'non_trading_day'

  if (!hasSectorData && !sectorError) {
    if (enrichedSelectedBoards.length && !sectorBoards.length) {
      sectorError = `分组内 ${enrichedSelectedBoards.length} 个板块，请勾选最多 ${MAX_CHART_SECTORS} 条曲线展示`
    } else if (sectorBoards.length) {
      sectorError = `图表展示 ${sectorBoards.length} 个板块，但 ${sectorDate} 暂无资金曲线数据`
    } else if (!activeGroupId) {
      sectorError = `尚未创建板块分组，请点击「管理分组」创建`
    } else if (!enrichedSelectedBoards.length) {
      sectorError = `分组「${activeGroupName ?? ''}」为空，请添加板块`
    }
  }

  let stockHint: string | undefined
  if (stockSourceMode === 'linkage' && !linkageSectorId) {
    stockHint = '点击左侧板块查看成分股主力（默认前 60）'
  } else if (stockSourceMode === 'linkage' && linkageSectorId && !stockSeries.length) {
    stockHint = '该板块暂无成分股采样数据'
  } else if (stockSourceMode === 'selected' && !stockTargets.length) {
    stockHint = '尚未添加自选个股，请点击「管理自选」添加'
  }

  const sectorHint =
    !activeGroupId
      ? '尚未创建板块分组，请点击「管理分组」'
      : !enrichedSelectedBoards.length
        ? `分组「${activeGroupName ?? ''}」为空，请添加板块`
        : missingSectorBoards.length
          ? `${missingSectorBoards.length} 个板块暂无 ${sectorDate} 曲线：${missingSectorBoards
              .slice(0, 3)
              .map((b) => b.name)
              .join('、')}${missingSectorBoards.length > 3 ? '…' : ''}（需等待采集器补采）`
          : enrichedSelectedBoards.length > sectorBoards.length
            ? `${activeGroupName ?? '分组'} ${enrichedSelectedBoards.length} · 曲线 ${sectorBoards.length}/${MAX_CHART_SECTORS}`
            : undefined

  return {
    updated_at: new Date().toISOString(),
    error: sectorError,
    disclaimer: '板块/个股主力来自 Workbench 采集聚合；分时数据依赖分钟采样批次。',
    host: 'workbench',
    board_type: 'GN',
    sector_mode: sectorMode,
    active_sector_group_id: activeGroupId,
    active_sector_group_name: activeGroupName,
    imported_sector_boards: finalImportedBoards,
    selected_boards: finalSelectedBoards,
    stock_mode: stockMode,
    selected_stocks: stockSourceMode === 'selected' ? stockTargets : [],
    watchlist: stockBundle.watchlist,
    timeline,
    sector_series: sectorSeries,
    stock_timeline: stockTimeline,
    stock_series: stockSeries,
    stock_view_date: stockDate,
    sector_view_date: sectorDate,
    stock_intraday_dates: replayDates,
    sector_intraday_dates: replayDates,
    intraday_retention_days: 30,
    trading_session: {
      tradeDate: calendarToday,
      currentMinute: latestMinute ?? rankingMinute,
      marketStatus,
      sessionStatus:
        marketStatus === 'open'
          ? 'open'
          : marketStatus === 'lunch_break'
            ? 'lunch_break'
            : marketStatus === 'closed'
              ? 'closed'
              : 'idle',
      isTradingDay: isWeekdayDate(sectorDate),
      message:
        sectorError ??
        sectorHint ??
        stockHint ??
        (marketStatus === 'lunch_break'
          ? '午间休市，暂停实时刷新'
          : marketStatus === 'closed' && isToday
            ? `今日收盘 · 数据截至 ${latestMinute ?? rankingMinute}`
            : marketStatus === 'pre_open'
              ? '尚未开盘'
              : hasSectorData
                ? `数据截至 ${latestMinute ?? rankingMinute}`
                : hasLiveMinute
                  ? `采集进行中，最新 ${latestMinute ?? rankingMinute}`
                  : undefined),
    },
  }
}

let sectorCatalogCache: { sector_id: string; name: string; sector_type: string }[] | null = null

async function loadSectorCatalogCache() {
  if (!sectorCatalogCache) {
    const response = await fetchSectors()
    sectorCatalogCache = Array.isArray(response.items) ? response.items : []
  }
  return sectorCatalogCache
}

export function invalidateSectorCatalogCache() {
  sectorCatalogCache = null
}

export async function fetchWorkbenchBoardCatalog(
  type: BoardCatalogType,
  q = '',
  limit = 1200,
): Promise<CatalogResponse> {
  const filterType = BOARD_TYPE_FILTER[type]
  const rawQuery = String(q ?? '').trim()
  const query = rawQuery.toLowerCase()
  const isCodeQuery = /^\d{6}$/.test(rawQuery)
  const isClassicQuery = isClassicIndexCodeQuery(rawQuery)

  let items: { sector_id: string; name: string; sector_type: string }[]
  if (query) {
    const response = await fetchSectors({ q: rawQuery, limit: Math.min(limit, 200) })
    items = Array.isArray(response.items) ? response.items : []
  } else {
    items = await loadSectorCatalogCache()
  }

  let filtered = items
  if (isClassicQuery) {
    filtered = items.filter((item) => item.sector_type === 'classic_index')
  } else if (filterType) {
    filtered = items.filter((item) => item.sector_type === filterType)
  }
  let boards = filtered.map((item) => toBoardItem(item))
  if (query && !isCodeQuery) {
    boards = boards.filter(
      (board) => board.name.toLowerCase().includes(query) || board.id.includes(query),
    )
  }
  const searchHint = query && !boards.length ? legacySectorSearchHint(rawQuery, type) : null
  return { boards: boards.slice(0, limit), type, searchHint: searchHint ?? undefined }
}

export async function fetchWorkbenchSelectedBoards(): Promise<SelectedBoardsResponse> {
  const boards = loadSelectedBoards()
  return { boards }
}

export async function saveWorkbenchSelectedBoards(boards: BoardItem[]): Promise<void> {
  saveSelectedBoardsLocal(boards)
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
