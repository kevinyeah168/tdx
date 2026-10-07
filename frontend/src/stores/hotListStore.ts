import { defineStore } from 'pinia'

import {
  fetchHotBoards,
  fetchHotStocks,
  type HotBoardListResponse,
  type HotBoardType,
  type HotStockBoard,
  type HotStockListResponse,
  type HotStockSource,
} from '@/api/hotList'
import { HOT_LIST_POLL_MS } from '@/constants/refresh'

/** Match backend CACHE_TTL_SECONDS; avoid redundant API calls on tab re-entry. */
const MIN_REFRESH_INTERVAL_MS = HOT_LIST_POLL_MS

export const useHotListStore = defineStore('hotList', {
  state: () => ({
    stockBoard: 'popularity' as HotStockBoard,
    stockSource: 'both' as HotStockSource,
    boardType: 'concept' as HotBoardType,
    stockData: null as HotStockListResponse | null,
    boardData: null as HotBoardListResponse | null,
    stockLoading: false,
    boardLoading: false,
    stockError: '',
    boardError: '',
    bootstrapped: false,
    lastRefreshedAt: 0,
  }),

  getters: {
    loading: (state) => state.stockLoading || state.boardLoading,
    error: (state) => state.stockError || state.boardError,
  },

  actions: {
    setStockBoard(board: HotStockBoard) {
      this.stockBoard = board
      void this.loadStocks()
    },

    setStockSource(source: HotStockSource) {
      this.stockSource = source
      void this.loadStocks()
    },

    setBoardType(boardType: HotBoardType) {
      this.boardType = boardType
      void this.loadBoards()
    },

    async bootstrap() {
      if (this.bootstrapped) {
        await this.refresh()
        return
      }
      this.bootstrapped = true
      await this.refresh({ force: true })
    },

    async refresh(options: { force?: boolean } = {}) {
      const force = options.force ?? false
      if (
        !force &&
        this.lastRefreshedAt > 0 &&
        Date.now() - this.lastRefreshedAt < MIN_REFRESH_INTERVAL_MS
      ) {
        return
      }
      this.stockError = ''
      this.boardError = ''
      await Promise.all([this.loadStocks(), this.loadBoards()])
      this.lastRefreshedAt = Date.now()
    },

    async loadStocks() {
      this.stockLoading = true
      this.stockError = ''
      try {
        this.stockData = await fetchHotStocks(this.stockBoard, this.stockSource)
      } catch (error) {
        this.stockError = error instanceof Error ? error.message : '加载个股热榜失败'
        this.stockData = null
      } finally {
        this.stockLoading = false
      }
    },

    async loadBoards() {
      this.boardLoading = true
      this.boardError = ''
      try {
        this.boardData = await fetchHotBoards(this.boardType)
      } catch (error) {
        this.boardError = error instanceof Error ? error.message : '加载板块热榜失败'
        this.boardData = null
      } finally {
        this.boardLoading = false
      }
    },
  },
})
