import {
  fetchBoard,
  fetchBoardCatalog,
  fetchSelectedStocks,
  fetchStockCatalog,
  refreshBoardData,
  saveSelectedStocks,
} from '@/api/board'
import {
  fetchSectorGroups,
  setActiveSectorGroup as persistActiveSectorGroup,
  setSectorGroupMemberChartVisible,
  type SectorGroup,
} from '@/api/sectorGroups'
import { fetchCustomSectors } from '@/api/customSectors'
import { fetchSectorCatalogMembers, fetchSectorGrayFlow } from '@/api/sectors'
import {
  attachGrayToFlowSeries,
  loadAutoSectorCount,
  loadLinkageTopK,
  loadStockSourceMode,
  MAX_CHART_SECTORS,
  chartVisibleCount,
  saveAutoSectorCount,
  saveLinkageTopK,
  saveSectorSourceMode,
  saveStockSourceMode,
  fetchWorkbenchStockPanel,
  refreshWorkbenchRankingSnapshot,
  type SectorSourceMode,
  type StockSourceMode,
} from '@/api/workbenchBoard'
import { shouldFetchMarketDataForDate } from '@/utils/tradingSession'
import { useMarketStore } from '@/stores/marketStore'
import { useReplayStore } from '@/stores/replayStore'
import { useSectorStore } from '@/stores/sectorStore'
import { WORKBENCH_REFRESH_SECONDS } from '@/constants/refresh'
import { todayTradeDate } from '@/utils/tradeDate'
import type {
  BoardCatalogType,
  BoardItem,
  BoardPayload,
  FlowSeries,
  ViewTab,
} from '@/types/board'
import { isClassicIndexCodeQuery } from '@/utils/sectorCodeAliases'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const emptyBoard = (): BoardPayload => ({
  updated_at: null,
  error: null,
  disclaimer: '',
  host: '',
  board_type: 'HY',
  sector_mode: 'auto',
  selected_boards: [],
  imported_sector_boards: [],
  stock_mode: 'linkage',
  selected_stocks: [],
  watchlist: [],
  timeline: [],
  sector_series: [],
  stock_timeline: [],
  stock_series: [],
  stock_view_date: null,
  sector_view_date: null,
  stock_intraday_dates: [],
  sector_intraday_dates: [],
  intraday_retention_days: 15,
  trading_session: null,
})

export const useBoardStore = defineStore('board', () => {
  const board = ref<BoardPayload>(emptyBoard())
  const loading = ref(false)
  const sectorLoading = ref(false)
  const sectorLoadingHint = ref('')
  const stockLoading = ref(false)
  const stockLoadingHint = ref('')
  const countdown = ref(WORKBENCH_REFRESH_SECONDS)
  const activeTab = ref<ViewTab>('sector')
  const highlightedSector = ref<string | null>(null)
  const highlightedStock = ref<string | null>(null)

  const sectorSourceMode = ref<SectorSourceMode>('selected')
  const stockSourceMode = ref<StockSourceMode>('linkage')
  saveSectorSourceMode('selected')
  if (loadStockSourceMode() !== 'linkage') {
    saveStockSourceMode('linkage')
  }
  const linkageSectorId = ref<string | null>(null)
  const linkageSectorName = ref<string | null>(null)
  const autoSectorCount = ref(loadAutoSectorCount())
  const linkageTopK = ref(loadLinkageTopK())
  if (linkageTopK.value === 20) {
    linkageTopK.value = 60
    saveLinkageTopK(linkageTopK.value)
  }
  if (autoSectorCount.value === 20) {
    autoSectorCount.value = 60
    saveAutoSectorCount(autoSectorCount.value)
  }
  const replayMinute = ref<string | null>(null)
  const chartHoverMinute = ref<string | null>(null)
  const chartHoverSource = ref<'sector' | 'stock' | null>(null)

  let stockLoadSeq = 0
  let sectorLoadSeq = 0
  let boardLoadChain: Promise<void> = Promise.resolve()
  let stockPanelLoadChain: Promise<void> = Promise.resolve()
  let cachedLinkageCatalogSignature = ''
  let cachedImportedSectorSignature = ''

  const isPanelBusy = computed(() => stockLoading.value || sectorLoading.value || loading.value)
  /** @deprecated alias — some callers still use isBoardBusy */
  const isBoardBusy = isPanelBusy

  const pickerOpen = ref(false)
  const pickerType = ref<BoardCatalogType>('ALL')
  const pickerQuery = ref('')
  const pickerCatalog = ref<BoardItem[]>([])
  const pickerSearchHint = ref<string | null>(null)
  const sectorGroups = ref<SectorGroup[]>([])
  const activeSectorGroupId = ref<string | null>(null)

  const stockPickerOpen = ref(false)
  const stockPickerQuery = ref('')
  const stockPickerCatalog = ref<BoardItem[]>([])
  const stockPickerSelected = ref<BoardItem[]>([])
  const stockPickerSaving = ref(false)
  const stockViewDate = ref<string | null>(null)
  const sectorViewDate = ref<string | null>(null)

  const sectorModeLabel = computed(
    () => board.value.active_sector_group_name || '板块分组',
  )

  const stockModeLabel = computed(() => {
    const linked = board.value.sector_series.find((item) => item.id === linkageSectorId.value)
    return linked ? `联动 · ${linked.name}` : '联动成分股'
  })

  const currentTimeline = computed(() =>
    activeTab.value === 'stock' ? board.value.stock_timeline : board.value.timeline,
  )

  const currentSeries = computed<FlowSeries[]>(() =>
    activeTab.value === 'stock' ? board.value.stock_series : board.value.sector_series,
  )

  function resolvedSectorViewDate(): string | null {
    return sectorViewDate.value ?? board.value.sector_view_date ?? null
  }

  function resolvedStockViewDate(): string | null {
    if (stockSourceMode.value === 'linkage') return resolvedSectorViewDate()
    return stockViewDate.value ?? board.value.stock_view_date ?? null
  }

  function effectiveStockViewDate(): string | null {
    return resolvedStockViewDate()
  }

  function boardFetchOptions() {
    const sectorDate = resolvedSectorViewDate()
    const stockDate = resolvedStockViewDate()
    const marketStore = useMarketStore()
    const replayStore = useReplayStore()
    return {
      stockDate,
      sectorDate,
      sectorSourceMode: sectorSourceMode.value,
      stockSourceMode: stockSourceMode.value,
      linkageSectorId: linkageSectorId.value,
      linkageSectorName: linkageSectorName.value,
      autoSectorCount: autoSectorCount.value,
      linkageTopK: linkageTopK.value,
      replayMinute: replayMinute.value,
      replayDates: replayStore.availableDates.length ? [...replayStore.availableDates] : undefined,
      marketOverview: sectorDate ? marketStore.overviewFor(sectorDate) : null,
    }
  }

  async function loadBoard(opts?: { stockSeq?: number; sectorSeq?: number }) {
    chartHoverMinute.value = null
    chartHoverSource.value = null
    let release!: () => void
    const slot = new Promise<void>((resolve) => {
      release = resolve
    })
    const previous = boardLoadChain
    boardLoadChain = slot
    // Snapshot seq before await/fetch so a later linkage click can invalidate stock/sector writes.
    const stockSeqAtStart = opts?.stockSeq ?? stockLoadSeq
    const sectorSeqAtStart = opts?.sectorSeq ?? sectorLoadSeq
    await previous
    try {
      const sectorDate = resolvedSectorViewDate()
      if (sectorDate) {
        await useMarketStore().ensureOverview(sectorDate)
      }
      const data = await fetchBoard({
        ...boardFetchOptions(),
        onSectorChartsReady: (partial) => {
          if (stockLoadSeq !== stockSeqAtStart) return
          if (sectorLoadSeq !== sectorSeqAtStart) return
          board.value = {
            ...board.value,
            ...partial,
            error: null,
          }
        },
        onSectorGrayReady: (partial) => {
          if (stockLoadSeq !== stockSeqAtStart) return
          if (sectorLoadSeq !== sectorSeqAtStart) return
          const grayById = new Map(
            [...partial.imported_sector_boards, ...partial.selected_boards].map((board) => [
              board.id,
              board.cum_gray ?? null,
            ]),
          )
          board.value = {
            ...board.value,
            imported_sector_boards: (board.value.imported_sector_boards ?? []).map((board) => ({
              ...board,
              cum_gray: grayById.get(board.id) ?? board.cum_gray ?? null,
            })),
            selected_boards: (board.value.selected_boards ?? []).map((board) => ({
              ...board,
              cum_gray: grayById.get(board.id) ?? board.cum_gray ?? null,
            })),
            sector_series: board.value.sector_series.map((series) => ({
              ...series,
              cum_gray: grayById.get(series.id) ?? series.cum_gray ?? null,
            })),
          }
        },
      })
      if (opts?.stockSeq != null && opts.stockSeq !== stockLoadSeq) return
      if (opts?.sectorSeq != null && opts.sectorSeq !== sectorLoadSeq) return

      // Dedicated stock/sector loads may finish first; never clobber them with a stale full board.
      const keepStock = stockLoadSeq !== stockSeqAtStart
      const keepSector = sectorLoadSeq !== sectorSeqAtStart
      activeSectorGroupId.value = data.active_sector_group_id ?? null
      if (data.sector_groups?.length) {
        sectorGroups.value = data.sector_groups
      }
      const resolvedSectorDate = sectorViewDate.value ?? data.sector_view_date ?? null
      if (!sectorViewDate.value && resolvedSectorDate) {
        sectorViewDate.value = resolvedSectorDate
      }
      const resolvedStockDate =
        stockSourceMode.value === 'linkage'
          ? resolvedSectorDate
          : stockViewDate.value ?? data.stock_view_date ?? null
      if (stockSourceMode.value === 'linkage' && resolvedStockDate) {
        stockViewDate.value = resolvedStockDate
      }
      board.value = {
        ...data,
        error: data.error ?? null,
        sector_view_date: resolvedSectorDate,
        stock_view_date: resolvedStockDate,
        ...(keepStock
          ? {
              stock_series: board.value.stock_series,
              stock_timeline: board.value.stock_timeline,
              watchlist: board.value.watchlist,
              stock_mode: board.value.stock_mode,
              selected_stocks: board.value.selected_stocks,
            }
          : {}),
        ...(keepSector
          ? {
              sector_series: board.value.sector_series,
              timeline: board.value.timeline,
              selected_boards: board.value.selected_boards,
              imported_sector_boards: board.value.imported_sector_boards,
            }
          : {}),
      }
      cachedImportedSectorSignature = importedSectorSignature(
        (board.value.imported_sector_boards ?? []).map((item) => item.id),
      )
      // View dates are controlled by panel pickers / TopBar — do not clobber from a stale response.
    } catch (error) {
      if (opts?.stockSeq != null && opts.stockSeq !== stockLoadSeq) return
      if (opts?.sectorSeq != null && opts.sectorSeq !== sectorLoadSeq) return
      board.value = {
        ...board.value,
        error: error instanceof Error ? error.message : String(error),
      }
    } finally {
      release()
    }
  }

  function linkageMemberSignature(symbols: string[]): string {
    return symbols
      .map((symbol) => symbol.toUpperCase())
      .sort()
      .join(',')
  }

  function resetLinkageCatalogSignature() {
    cachedLinkageCatalogSignature = ''
  }

  async function loadStockPanel(opts?: { stockSeq?: number }) {
    let release!: () => void
    const slot = new Promise<void>((resolve) => {
      release = resolve
    })
    const previous = stockPanelLoadChain
    stockPanelLoadChain = slot
    await previous
    try {
      const data = await fetchWorkbenchStockPanel(boardFetchOptions())
      if (opts?.stockSeq != null && opts.stockSeq !== stockLoadSeq) return
      board.value = {
        ...board.value,
        error: null,
        stock_series: data.stock_series,
        stock_timeline: data.stock_timeline,
        watchlist: data.watchlist,
        stock_mode: data.stock_mode,
        selected_stocks: data.selected_stocks,
        stock_view_date: resolvedStockViewDate() ?? data.stock_view_date,
      }
      cachedLinkageCatalogSignature = linkageMemberSignature(
        (data.watchlist ?? []).map((item) => item.symbol),
      )
    } catch (error) {
      if (opts?.stockSeq != null && opts.stockSeq !== stockLoadSeq) return
      board.value = {
        ...board.value,
        error: error instanceof Error ? error.message : String(error),
      }
    } finally {
      release()
    }
  }

  function importedSectorSignature(sectorIds: string[]): string {
    return sectorIds
      .map((id) => id.trim())
      .filter(Boolean)
      .sort()
      .join(',')
  }

  /** Reload board when directory-imported custom sectors change (file sync). */
  async function refreshImportedSectorsIfChanged() {
    try {
      const { items } = await fetchCustomSectors()
      const signature = importedSectorSignature(
        items.filter((item) => item.source_type === 'directory').map((item) => item.sector_id),
      )
      if (signature === cachedImportedSectorSignature) return
      cachedImportedSectorSignature = signature
      await loadBoard()
    } catch {
      /* background refresh should not surface */
    }
  }

  async function refreshHomeCatalogIfChanged() {
    await refreshLinkageCatalogIfChanged()
    await refreshImportedSectorsIfChanged()
  }

  /** Lightweight poll: reload stock panel only when linkage catalog members changed. */
  async function refreshLinkageCatalogIfChanged() {
    if (stockSourceMode.value !== 'linkage' || !linkageSectorId.value) return

    const sectorDate = resolvedSectorViewDate()
    if (!sectorDate || !shouldFetchMarketDataForDate(sectorDate)) return

    try {
      const catalog = await fetchSectorCatalogMembers(
        linkageSectorId.value,
        linkageSectorName.value ?? undefined,
      )
      const signature = linkageMemberSignature(catalog.items.map((item) => item.symbol))
      const current = linkageMemberSignature((board.value.watchlist ?? []).map((item) => item.symbol))
      if (signature === cachedLinkageCatalogSignature && signature === current) return
      cachedLinkageCatalogSignature = signature
      await loadStockPanel()
    } catch {
      /* background refresh should not surface */
    }
  }

  function clearStockPanelPreview() {
    highlightedStock.value = null
    board.value = {
      ...board.value,
      stock_series: [],
      stock_timeline: [],
      watchlist: [],
    }
  }

  function clearSectorPanelPreview() {
    highlightedSector.value = null
    board.value = {
      ...board.value,
      sector_series: [],
      timeline: [],
    }
  }

  async function withStockLoading(hint: string, task: (seq: number) => Promise<void>) {
    const seq = ++stockLoadSeq
    stockLoading.value = true
    stockLoadingHint.value = hint
    try {
      await task(seq)
    } finally {
      if (seq === stockLoadSeq) {
        stockLoading.value = false
        stockLoadingHint.value = ''
      }
    }
  }

  async function withSectorLoading(hint: string, task: (seq: number) => Promise<void>) {
    const seq = ++sectorLoadSeq
    sectorLoading.value = true
    sectorLoadingHint.value = hint
    try {
      await task(seq)
    } finally {
      if (seq === sectorLoadSeq) {
        sectorLoading.value = false
        sectorLoadingHint.value = ''
      }
    }
  }

  async function setStockViewDate(date: string) {
    if (stockSourceMode.value === 'linkage') {
      await setSectorViewDate(date)
      return
    }
    stockViewDate.value = date
    loading.value = true
    try {
      await withStockLoading('切换交易日…', async (seq) => {
        const data = await fetchBoard({ ...boardFetchOptions(), stockDate: date })
        if (seq !== stockLoadSeq) return
        board.value = {
          ...data,
          stock_view_date: date,
          sector_view_date: sectorViewDate.value ?? data.sector_view_date,
        }
      })
    } finally {
      loading.value = false
    }
  }

  async function setSectorViewDate(date: string) {
    sectorViewDate.value = date
    if (stockSourceMode.value === 'linkage') {
      stockViewDate.value = date
    }
    loading.value = true
    try {
      await loadBoard()
    } finally {
      loading.value = false
    }
  }

  async function setSectorSourceMode(mode: SectorSourceMode) {
    if (mode !== 'selected') mode = 'selected'
    sectorSourceMode.value = 'selected'
    saveSectorSourceMode('selected')
    loading.value = true
    try {
      await withSectorLoading('加载板块分组…', (seq) => loadBoard({ sectorSeq: seq }))
    } finally {
      loading.value = false
    }
  }

  async function loadSectorGroups() {
    try {
      const response = await fetchSectorGroups()
      sectorGroups.value = response.items
      activeSectorGroupId.value =
        response.active_group_id === 'all' ? null : response.active_group_id
    } catch {
      sectorGroups.value = []
    }
  }

  async function switchSectorGroup(groupId: string) {
    if (!groupId || groupId === activeSectorGroupId.value) return
    await withSectorLoading('切换分组…', async (seq) => {
      await persistActiveSectorGroup(groupId)
      activeSectorGroupId.value = groupId
      const sectorStore = useSectorStore()
      await sectorStore.loadGroups()
      await loadBoard({ sectorSeq: seq })
    })
  }

  async function setStockSourceMode(mode: StockSourceMode) {
    // Right panel defaults to linkage (top members of clicked sector).
    stockSourceMode.value = 'linkage'
    saveStockSourceMode('linkage')
    if (mode === 'selected') {
      await openStockPicker()
      return
    }
    loading.value = true
    try {
      await withStockLoading('切换至联动模式…', (seq) => loadBoard({ stockSeq: seq }))
    } finally {
      loading.value = false
    }
  }

  function clearBoardError() {
    if (board.value.error) {
      board.value = { ...board.value, error: null }
    }
  }

  function syncReplayDates(tradeDate: string, minute: string | null) {
    sectorViewDate.value = tradeDate
    stockViewDate.value = tradeDate
    replayMinute.value = minute
    clearBoardError()
  }

  async function setReplayContext(tradeDate: string, minute: string | null) {
    // Top-bar global date: sync both panels only when the global date actually changes.
    const sectorChanged = sectorViewDate.value !== tradeDate
    const stockChanged = stockViewDate.value !== tradeDate
    sectorViewDate.value = tradeDate
    stockViewDate.value = tradeDate
    replayMinute.value = minute
    if (sectorChanged || stockChanged || !board.value.sector_series.length) {
      await loadBoard()
    }
  }

  /** Live-mode minute tick: never overwrite panel-selected historical dates. */
  async function syncReplayMinute(minute: string | null) {
    replayMinute.value = minute
    if (!minute) return
    if (isHistoricalSectorView() && isHistoricalStockView()) return

    if (!board.value.sector_series.length) {
      await loadBoard()
      return
    }

    const sectorDate = resolvedSectorViewDate()
    if (!sectorDate || !shouldFetchMarketDataForDate(sectorDate)) return

    try {
      const refreshed = await refreshWorkbenchRankingSnapshot({
        sectorDate,
        rankingMinute: minute,
        importedBoards: board.value.imported_sector_boards ?? [],
        selectedBoards: board.value.selected_boards ?? [],
        sectorSeries: board.value.sector_series ?? [],
        stockSeries: board.value.stock_series ?? [],
        watchlist: board.value.watchlist ?? [],
        stockSourceMode: stockSourceMode.value,
        linkageSectorId: linkageSectorId.value,
        linkageSectorName: linkageSectorName.value,
        linkageTopK: linkageTopK.value,
      })
      board.value = {
        ...board.value,
        ...refreshed,
      }
    } catch {
      /* keep stale ranking */
    }
  }

  function isHistoricalSectorView(): boolean {
    const date = resolvedSectorViewDate()
    return Boolean(date && date !== todayTradeDate())
  }

  function isHistoricalStockView(): boolean {
    const date = effectiveStockViewDate()
    return Boolean(date && date !== todayTradeDate())
  }

  async function selectSectorForLinkage(sectorId: string) {
    stockSourceMode.value = 'linkage'
    saveStockSourceMode('linkage')

    const sameLinkage = linkageSectorId.value === sectorId
    const sectorSoloActive = highlightedSector.value === sectorId
    const hasLinkedStockData = (board.value.stock_series?.length ?? 0) > 0

    // 已联动同一板块：只切换左侧 solo，不重复拉成分股
    if (sameLinkage && !highlightedStock.value) {
      if (sectorSoloActive) {
        highlightedSector.value = null
        return
      }
      if (hasLinkedStockData) {
        highlightedSector.value = sectorId
        return
      }
    }

    // 切换板块后必须清掉个股 solo，否则会一直只画一条旧曲线
    highlightedStock.value = null
    highlightedSector.value = sectorId
    void ensureSectorGrayOverlay(sectorId)

    const sectorName =
      board.value.sector_series.find((item) => item.id === sectorId)?.name ||
      board.value.selected_boards.find((item) => item.id === sectorId)?.name ||
      sectorId

    const linkageChanged = !sameLinkage
    linkageSectorId.value = sectorId
    linkageSectorName.value = sectorName
    if (linkageChanged) resetLinkageCatalogSignature()

    const tradeDate = resolvedSectorViewDate()
    if (tradeDate) {
      stockViewDate.value = tradeDate
    }

    // Bump seq first so any in-flight loadBoard keeps its older snapshot and won't wipe stocks.
    const seq = ++stockLoadSeq
    stockLoading.value = true
    stockLoadingHint.value = `加载 ${sectorName} 前 ${linkageTopK.value} 成分股…`

    // Switching sector: clear old curves immediately (avoid flash of previous members).
    if (linkageChanged) {
      board.value = {
        ...board.value,
        stock_series: [],
        stock_timeline: [],
        watchlist: [],
      }
    }

    try {
      await loadStockPanel({ stockSeq: seq })
    } finally {
      if (seq === stockLoadSeq) {
        stockLoading.value = false
        stockLoadingHint.value = ''
      }
    }
  }

  async function loadCatalog() {
    const query = String(pickerQuery.value ?? '').trim()
    if (isClassicIndexCodeQuery(query) && pickerType.value !== 'IDX') {
      pickerType.value = 'IDX'
      return
    }
    try {
      const data = await fetchBoardCatalog(pickerType.value, query)
      pickerCatalog.value = data.boards || []
      pickerSearchHint.value = data.searchHint ?? null
    } catch (error) {
      pickerCatalog.value = []
      pickerSearchHint.value =
        error instanceof Error ? `加载板块目录失败：${error.message}` : '加载板块目录失败'
    }
  }

  async function openPicker() {
    pickerOpen.value = true
    pickerSearchHint.value = null
    await Promise.all([loadSectorGroups(), loadCatalog()])
  }

  async function closePicker(reload = false) {
    pickerOpen.value = false
    if (reload) {
      await withSectorLoading('刷新板块分组…', (seq) => loadBoard({ sectorSeq: seq }))
    }
  }

  async function toggleSectorChartVisible(sectorId: string, visible: boolean) {
    const groupId = board.value.active_sector_group_id
    if (!groupId) return
    if (visible && chartVisibleCount(board.value.selected_boards ?? []) >= MAX_CHART_SECTORS) {
      return
    }
    try {
      await setSectorGroupMemberChartVisible(groupId, sectorId, visible)
      await withSectorLoading('更新图表…', (seq) => loadBoard({ sectorSeq: seq }))
    } catch {
      /* optional */
    }
  }

  async function loadStockCatalog() {
    const data = await fetchStockCatalog(stockPickerQuery.value.trim())
    stockPickerCatalog.value = data.stocks || []
  }

  async function openStockPicker() {
    stockPickerOpen.value = true
    const data = await fetchSelectedStocks()
    stockPickerSelected.value = [...(data.stocks || [])]
    await loadStockCatalog()
  }

  function closeStockPicker() {
    stockPickerOpen.value = false
  }

  function toggleStockPick(item: BoardItem) {
    const idx = stockPickerSelected.value.findIndex((s) => s.id === item.id)
    if (idx >= 0) stockPickerSelected.value.splice(idx, 1)
    else stockPickerSelected.value.push({ id: item.id, name: item.name })
  }

  function isStockPicked(id: string) {
    return stockPickerSelected.value.some((s) => s.id === id)
  }

  async function saveStockPicker() {
    stockPickerSaving.value = true
    try {
      await saveSelectedStocks(stockPickerSelected.value)
      stockPickerOpen.value = false
      if (!stockPickerSelected.value.length) {
        await setStockSourceMode('linkage')
        return
      }
      if (stockSourceMode.value !== 'selected') {
        await setStockSourceMode('selected')
        return
      }
      await withStockLoading('刷新自选个股…', (seq) => loadBoard({ stockSeq: seq }))
    } finally {
      stockPickerSaving.value = false
    }
  }

  async function clearStockPicker() {
    stockPickerSelected.value = []
    await saveSelectedStocks([])
    stockPickerOpen.value = false
    await setStockSourceMode('linkage')
  }

  async function manualRefresh() {
    loading.value = true
    try {
      await refreshBoardData()
      await loadBoard()
      countdown.value = WORKBENCH_REFRESH_SECONDS
    } finally {
      loading.value = false
    }
  }

  function setTab(tab: ViewTab) {
    activeTab.value = tab
    highlightedSector.value = null
    highlightedStock.value = null
    chartHoverMinute.value = null
    chartHoverSource.value = null
  }

  async function ensureSectorGrayOverlay(sectorId: string) {
    const timeline = board.value.timeline || []
    const existing = board.value.sector_series.find((item) => item.id === sectorId)
    if (!existing || existing.gray_values?.some((value) => value != null)) return
    const sectorDate = resolvedSectorViewDate()
    if (!sectorDate) return
    try {
      const payload = await fetchSectorGrayFlow(sectorId, sectorDate)
      if (!payload.points.length) return
      const patched = attachGrayToFlowSeries(existing, payload.points, timeline)
      board.value = {
        ...board.value,
        sector_series: board.value.sector_series.map((item) =>
          item.id === sectorId ? patched : item,
        ),
      }
    } catch {
      /* gray optional */
    }
  }

  function toggleHighlight(id: string, mode: 'sector' | 'stock' = 'sector') {
    if (mode === 'stock') {
      highlightedStock.value = highlightedStock.value === id ? null : id
      return
    }
    const next = highlightedSector.value === id ? null : id
    highlightedSector.value = next
    if (next) void ensureSectorGrayOverlay(next)
  }

  function selectStock(symbol: string) {
    highlightedStock.value = highlightedStock.value === symbol ? null : symbol
  }

  function resetCountdown() {
    countdown.value = WORKBENCH_REFRESH_SECONDS
  }

  function tickCountdown() {
    countdown.value = Math.max(0, countdown.value - 1)
  }

  function sortedSectors(): FlowSeries[] {
    return [...board.value.sector_series].sort(
      (a, b) => Number(b.cum_main || 0) - Number(a.cum_main || 0),
    )
  }

  function sortedStocks(): FlowSeries[] {
    return [...board.value.stock_series].sort(
      (a, b) => Number(b.cum_main || 0) - Number(a.cum_main || 0),
    )
  }

  function setAutoSectorCount(count: number) {
    autoSectorCount.value = count
    saveAutoSectorCount(count)
  }

  function setLinkageTopK(topK: number) {
    linkageTopK.value = topK
    saveLinkageTopK(topK)
  }

  function setChartHoverMinute(minute: string | null, source: 'sector' | 'stock') {
    if (!minute) {
      clearChartHover(source)
      return
    }
    if (chartHoverMinute.value === minute && chartHoverSource.value === source) return
    chartHoverMinute.value = minute
    chartHoverSource.value = source
  }

  function clearChartHover(source?: 'sector' | 'stock') {
    if (source && chartHoverSource.value !== source) return
    chartHoverMinute.value = null
    chartHoverSource.value = null
  }

  return {
    board,
    loading,
    sectorLoading,
    sectorLoadingHint,
    stockLoading,
    stockLoadingHint,
    countdown,
    activeTab,
    highlightedSector,
    highlightedStock,
    sectorSourceMode,
    stockSourceMode,
    linkageSectorId,
    linkageSectorName,
    autoSectorCount,
    linkageTopK,
    replayMinute,
    chartHoverMinute,
    chartHoverSource,
    pickerOpen,
    pickerType,
    pickerQuery,
    pickerCatalog,
    pickerSearchHint,
    sectorGroups,
    activeSectorGroupId,
    stockPickerOpen,
    stockPickerQuery,
    stockPickerCatalog,
    stockPickerSelected,
    stockPickerSaving,
    stockViewDate,
    sectorViewDate,
    sectorModeLabel,
    stockModeLabel,
    currentTimeline,
    currentSeries,
    isPanelBusy,
    isBoardBusy,
    loadBoard,
    loadStockPanel,
    refreshLinkageCatalogIfChanged,
    refreshHomeCatalogIfChanged,
    loadCatalog,
    openPicker,
    closePicker,
    loadSectorGroups,
    switchSectorGroup,
    toggleSectorChartVisible,
    loadStockCatalog,
    openStockPicker,
    closeStockPicker,
    toggleStockPick,
    isStockPicked,
    saveStockPicker,
    clearStockPicker,
    setStockViewDate,
    setSectorViewDate,
    setSectorSourceMode,
    setStockSourceMode,
    setReplayContext,
    syncReplayDates,
    clearBoardError,
    syncReplayMinute,
    isHistoricalSectorView,
    isHistoricalStockView,
    selectSectorForLinkage,
    manualRefresh,
    setTab,
    toggleHighlight,
    selectStock,
    resetCountdown,
    tickCountdown,
    sortedSectors,
    sortedStocks,
    setAutoSectorCount,
    setLinkageTopK,
    setChartHoverMinute,
    clearChartHover,
  }
})
