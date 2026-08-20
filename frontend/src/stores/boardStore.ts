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

import type {

  BoardCatalogType,

  BoardItem,

  BoardPayload,

  FlowSeries,

  ViewTab,

} from '@/types/board'

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

  stock_mode: 'empty',

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

  const countdown = ref(6)

  const activeTab = ref<ViewTab>('sector')

  const highlightedSector = ref<string | null>(null)

  const highlightedStock = ref<string | null>(null)



  const pickerOpen = ref(false)

  const pickerType = ref<BoardCatalogType>('HY')

  const pickerQuery = ref('')

  const pickerCatalog = ref<BoardItem[]>([])

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

    board.value.sector_mode === 'selected' ? '自选板块' : '自动榜',

  )



  const stockModeLabel = computed(() =>

    board.value.stock_mode === 'selected' ? '自选个股' : '未选个股',

  )



  const currentTimeline = computed(() =>

    activeTab.value === 'stock' ? board.value.stock_timeline : board.value.timeline,

  )



  const currentSeries = computed<FlowSeries[]>(() =>

    activeTab.value === 'stock' ? board.value.stock_series : board.value.sector_series,

  )



  async function loadBoard() {

    const data = await fetchBoard({

      stockDate: stockViewDate.value,

      sectorDate: sectorViewDate.value,

    })

    board.value = data

    if (data.stock_view_date) stockViewDate.value = data.stock_view_date

    if (data.sector_view_date) sectorViewDate.value = data.sector_view_date

  }



  async function setStockViewDate(date: string) {

    stockViewDate.value = date

    loading.value = true

    try {

      board.value = await fetchBoard({ stockDate: date, sectorDate: sectorViewDate.value })

      if (board.value.stock_view_date) stockViewDate.value = board.value.stock_view_date

    } finally {

      loading.value = false

    }

  }



  async function setSectorViewDate(date: string) {

    sectorViewDate.value = date

    loading.value = true

    try {

      board.value = await fetchBoard({ stockDate: stockViewDate.value, sectorDate: date })

      if (board.value.sector_view_date) sectorViewDate.value = board.value.sector_view_date

    } finally {

      loading.value = false

    }

  }



  async function loadCatalog() {

    const data = await fetchBoardCatalog(pickerType.value, pickerQuery.value.trim())

    pickerCatalog.value = data.boards || []

  }



  async function openPicker() {

    pickerOpen.value = true

    const data = await fetchSelectedBoards()

    pickerSelected.value = [...(data.boards || [])]

    await loadCatalog()

  }



  function closePicker() {

    pickerOpen.value = false

  }



  function togglePick(item: BoardItem) {

    const idx = pickerSelected.value.findIndex((b) => b.id === item.id)

    if (idx >= 0) pickerSelected.value.splice(idx, 1)

    else pickerSelected.value.push({ id: item.id, name: item.name })

  }



  function isPicked(id: string) {

    return pickerSelected.value.some((b) => b.id === id)

  }



  async function savePicker() {

    pickerSaving.value = true

    try {

      await saveSelectedBoards(pickerSelected.value)

      pickerOpen.value = false

      await manualRefresh()

    } finally {

      pickerSaving.value = false

    }

  }



  async function clearPicker() {

    pickerSelected.value = []

    await savePicker()

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

      await manualRefresh()

    } finally {

      stockPickerSaving.value = false

    }

  }



  async function clearStockPicker() {

    stockPickerSelected.value = []

    await saveStockPicker()

  }



  async function manualRefresh() {

    loading.value = true

    try {

      await refreshBoardData()

      await loadBoard()

      countdown.value = 6

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

    countdown.value = 6

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



  return {

    board,

    loading,

    countdown,

    activeTab,

    highlightedSector,

    highlightedStock,

    pickerOpen,

    pickerType,

    pickerQuery,

    pickerCatalog,

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

    loadBoard,

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

    manualRefresh,

    setTab,

    toggleHighlight,

    selectStock,

    resetCountdown,

    tickCountdown,

    sortedSectors,

    sortedStocks,

  }

})


