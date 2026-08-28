import {
  fetchBoard,
  fetchBoardCatalog,
  fetchSelectedBoards,
  fetchSelectedStocks,
  fetchStockCatalog,
  refreshBoardData,
  saveSelectedBoards,
  saveSelectedStocks,
} from '@/api/board'
import {
  enrichBoardItems,
  loadAutoSectorCount,
  loadLinkageTopK,
  loadSectorSourceMode,
  loadSelectedBoards,
  loadSelectedStocks,
  loadStockSourceMode,
  saveAutoSectorCount,
  saveLinkageTopK,
  saveSectorSourceMode,
  saveStockSourceMode,
  syncLinkageSector,
  fetchWorkbenchStockPanel,
  type SectorSourceMode,
  type StockSourceMode,
} from '@/api/workbenchBoard'
import { WORKBENCH_REFRESH_SECONDS } from '@/constants/refresh'
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

  const sectorSourceMode = ref<SectorSourceMode>(loadSectorSourceMode())
  const stockSourceMode = ref<StockSourceMode>(loadStockSourceMode())
  const linkageSectorId = ref<string | null>(null)
  const linkageSectorName = ref<string | null>(null)
  const autoSectorCount = ref(loadAutoSectorCount())
  const linkageTopK = ref(loadLinkageTopK())
  const replayMinute = ref<string | null>(null)

  let stockLoadSeq = 0
  let sectorLoadSeq = 0
  let boardLoadChain: Promise<void> = Promise.resolve()

  const isPanelBusy = computed(() => stockLoading.value || sectorLoading.value || loading.value)

  const pickerOpen = ref(false)
  const pickerType = ref<BoardCatalogType>('HY')
  const pickerQuery = ref('')
  const pickerCatalog = ref<BoardItem[]>([])
  const pickerSearchHint = ref<string | null>(null)
  const pickerSelected = ref<BoardItem[]>([])
  const pickerSaving = ref(false)

  const stockPickerOpen = ref(false)
  const stockPickerQuery = ref('')
  const stockPickerCatalog = ref<BoardItem[]>([])
  const stockPickerSelected = ref<BoardItem[]>([])
  const stockPickerSaving = ref(false)
  const stockViewDate = ref<string | null>(null)
  const sectorViewDate = ref<string | null>(null)

  const sectorModeLabel = computed(() =>
    sectorSourceMode.value === 'selected'
      ? '自选板块'
      : `主力流入 · 前${autoSectorCount.value}`,
  )

  const stockModeLabel = computed(() => {
    if (stockSourceMode.value === 'linkage') {
      const linked = board.value.sector_series.find((item) => item.id === linkageSectorId.value)
      return linked ? `联动 · ${linked.name}` : '联动模式'
    }
    return board.value.stock_mode === 'selected' ? '自选个股' : '未选个股'
  })

  const currentTimeline = computed(() =>
    activeTab.value === 'stock' ? board.value.stock_timeline : board.value.timeline,
  )

  const currentSeries = computed<FlowSeries[]>(() =>
    activeTab.value === 'stock' ? board.value.stock_series : board.value.sector_series,
  )

  function boardFetchOptions() {
    return {
      stockDate: stockViewDate.value,
      sectorDate: sectorViewDate.value,
      sectorSourceMode: sectorSourceMode.value,
      stockSourceMode: stockSourceMode.value,
      linkageSectorId: linkageSectorId.value,
      linkageSectorName: linkageSectorName.value,
      autoSectorCount: autoSectorCount.value,
      linkageTopK: linkageTopK.value,
      replayMinute: replayMinute.value,
    }
  }

  async function loadBoard(opts?: { stockSeq?: number; sectorSeq?: number }) {
    let release!: () => void
    const slot = new Promise<void>((resolve) => {
      release = resolve
    })
    const previous = boardLoadChain
    boardLoadChain = slot
    await previous
    try {
      const data = await fetchBoard(boardFetchOptions())
      if (opts?.stockSeq != null && opts.stockSeq !== stockLoadSeq) return
      if (opts?.sectorSeq != null && opts.sectorSeq !== sectorLoadSeq) return
      board.value = { ...data, error: data.error ?? null }
      if (data.stock_view_date) stockViewDate.value = data.stock_view_date
      if (data.sector_view_date) sectorViewDate.value = data.sector_view_date
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

  async function loadStockPanel(opts?: { stockSeq?: number }) {
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
        stock_view_date: data.stock_view_date,
      }
      if (data.stock_view_date) stockViewDate.value = data.stock_view_date
    } catch (error) {
      if (opts?.stockSeq != null && opts.stockSeq !== stockLoadSeq) return
      board.value = {
        ...board.value,
        error: error instanceof Error ? error.message : String(error),
      }
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
    clearStockPanelPreview()
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
    clearSectorPanelPreview()
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
    stockViewDate.value = date
    loading.value = true
    try {
      await withStockLoading('切换交易日…', async (seq) => {
        const data = await fetchBoard({ ...boardFetchOptions(), stockDate: date })
        if (seq !== stockLoadSeq) return
        board.value = data
        if (data.stock_view_date) stockViewDate.value = data.stock_view_date
      })
    } finally {
      loading.value = false
    }
  }

  async function setSectorViewDate(date: string) {
    sectorViewDate.value = date
    loading.value = true
    try {
      await withSectorLoading('切换交易日…', async (seq) => {
        const data = await fetchBoard({ ...boardFetchOptions(), sectorDate: date })
        if (seq !== sectorLoadSeq) return
        board.value = data
        if (data.sector_view_date) sectorViewDate.value = data.sector_view_date
      })
    } finally {
      loading.value = false
    }
  }

  async function setSectorSourceMode(mode: SectorSourceMode) {
    if (sectorSourceMode.value === mode && mode === 'selected' && !loadSelectedBoards().length) {
      await openPicker()
      return
    }
    sectorSourceMode.value = mode
    saveSectorSourceMode(mode)
    loading.value = true
    try {
      const hint = mode === 'auto' ? '加载主力流入榜…' : '加载自选板块…'
      await withSectorLoading(hint, (seq) => loadBoard({ sectorSeq: seq }))
      if (mode === 'selected' && !loadSelectedBoards().length) {
        await openPicker()
      }
    } finally {
      loading.value = false
    }
  }

  async function setStockSourceMode(mode: StockSourceMode) {
    if (stockSourceMode.value === mode && mode === 'selected' && !loadSelectedStocks().length) {
      await openStockPicker()
      return
    }
    stockSourceMode.value = mode
    saveStockSourceMode(mode)
    if (mode === 'selected') {
      linkageSectorId.value = null
      linkageSectorName.value = null
    }
    loading.value = true
    try {
      const hint = mode === 'linkage' ? '切换至联动模式…' : '加载自选个股…'
      await withStockLoading(hint, (seq) => loadBoard({ stockSeq: seq }))
      if (mode === 'selected' && !loadSelectedStocks().length) {
        await openStockPicker()
      }
    } finally {
      loading.value = false
    }
  }

  async function setReplayContext(tradeDate: string, minute: string | null) {
    sectorViewDate.value = tradeDate
    stockViewDate.value = tradeDate
    replayMinute.value = minute
    await loadBoard()
  }

  async function selectSectorForLinkage(sectorId: string) {
    if (stockSourceMode.value !== 'linkage') {
      toggleHighlight(sectorId, 'sector')
      return
    }

    const sameLinkage = linkageSectorId.value === sectorId
    const sectorSoloActive = highlightedSector.value === sectorId

    // 再次点击已联动板块：仅取消左侧板块 solo，保留联动
    if (sameLinkage && sectorSoloActive && !highlightedStock.value) {
      highlightedSector.value = null
      return
    }

    // 切换板块后必须清掉个股 solo，否则会一直只画一条旧曲线
    highlightedStock.value = null
    highlightedSector.value = sectorId

    const sectorName =
      board.value.sector_series.find((item) => item.id === sectorId)?.name || sectorId

    const linkageChanged = !sameLinkage
    linkageSectorId.value = sectorId
    linkageSectorName.value = sectorName
    if (linkageChanged) {
      void syncLinkageSector(sectorId, sectorName)
    }

    const seq = ++stockLoadSeq
    stockLoading.value = true
    stockLoadingHint.value = `加载 ${sectorName} 成分股…`
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
    const query = pickerQuery.value.trim()
    if (isClassicIndexCodeQuery(query) && pickerType.value !== 'IDX') {
      pickerType.value = 'IDX'
      return
    }
    const data = await fetchBoardCatalog(pickerType.value, query)
    pickerCatalog.value = data.boards || []
    pickerSearchHint.value = data.searchHint ?? null
  }

  async function openPicker() {
    pickerOpen.value = true
    const data = await fetchSelectedBoards()
    try {
      const { fetchSectors } = await import('@/api/sectors')
      const sectors = await fetchSectors()
      pickerSelected.value = enrichBoardItems(data.boards || [], sectors.items)
    } catch {
      pickerSelected.value = [...(data.boards || [])]
    }
    await loadCatalog()
  }

  function closePicker() {
    pickerOpen.value = false
  }

  function togglePick(item: BoardItem) {
    const idx = pickerSelected.value.findIndex((b) => b.id === item.id)
    if (idx >= 0) pickerSelected.value.splice(idx, 1)
    else pickerSelected.value.push({ id: item.id, name: item.name, sector_type: item.sector_type })
  }

  function isPicked(id: string) {
    return pickerSelected.value.some((b) => b.id === id)
  }

  async function savePicker() {
    pickerSaving.value = true
    try {
      await saveSelectedBoards(pickerSelected.value)
      pickerOpen.value = false
      if (!pickerSelected.value.length) {
        await setSectorSourceMode('auto')
        return
      }
      if (sectorSourceMode.value !== 'selected') {
        await setSectorSourceMode('selected')
        return
      }
      await withSectorLoading('刷新自选板块…', (seq) => loadBoard({ sectorSeq: seq }))
    } finally {
      pickerSaving.value = false
    }
  }

  async function clearPicker() {
    pickerSelected.value = []
    await saveSelectedBoards([])
    pickerOpen.value = false
    await setSectorSourceMode('auto')
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
  }

  function toggleHighlight(id: string, mode: 'sector' | 'stock' = 'sector') {
    if (mode === 'stock') {
      highlightedStock.value = highlightedStock.value === id ? null : id
    } else {
      highlightedSector.value = highlightedSector.value === id ? null : id
    }
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
    pickerOpen,
    pickerType,
    pickerQuery,
    pickerCatalog,
    pickerSearchHint,
    pickerSelected,
    pickerSaving,
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
    loadBoard,
    loadStockPanel,
    loadCatalog,
    openPicker,
    closePicker,
    togglePick,
    isPicked,
    savePicker,
    clearPicker,
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
  }
})
