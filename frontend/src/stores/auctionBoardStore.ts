import { defineStore } from 'pinia'

import {
  AUCTION_BOARD_PAGE_SIZE,
  fetchAuctionBoard,
  type AuctionBoardResponse,
  type AuctionBoardScope,
  type AuctionBoardSort,
} from '@/api/auctionBoard'
import { AUCTION_POLL_MS } from '@/constants/refresh'
import { todayTradeDate } from '@/utils/tradeDate'

const MIN_REFRESH_INTERVAL_MS = AUCTION_POLL_MS

export const useAuctionBoardStore = defineStore('auctionBoard', {
  state: () => ({
    tradeDate: todayTradeDate(),
    sort: 'ratio' as AuctionBoardSort,
    scope: 'top' as AuctionBoardScope,
    searchQuery: '',
    page: 1,
    pageSize: AUCTION_BOARD_PAGE_SIZE,
    data: null as AuctionBoardResponse | null,
    loading: false,
    refreshing: false,
    error: '',
    bootstrapped: false,
    lastRefreshedAt: 0,
  }),

  getters: {
    isToday: (state) => state.tradeDate === todayTradeDate(),
    isSnapshot: (state) => state.data?.data_kind === 'snapshot',
    total: (state) => state.data?.total ?? 0,
    shouldPoll: (state) => {
      const phase = state.data?.phase
      return (
        state.tradeDate === todayTradeDate() &&
        (phase === 'waiting' || phase === 'auction' || phase === 'post_auction')
      )
    },
  },

  actions: {
    setTradeDate(tradeDate: string) {
      if (this.tradeDate === tradeDate) return
      this.tradeDate = tradeDate
      this.page = 1
      this.data = null
      void this.load({ force: true })
    },

    setSort(sort: AuctionBoardSort) {
      if (this.sort === sort) return
      this.sort = sort
      this.page = 1
      void this.load({ force: true })
    },

    setScope(scope: AuctionBoardScope) {
      if (this.scope === scope) return
      this.scope = scope
      this.page = 1
      const phase = this.data?.phase
      const forceMarket = scope === 'market' && phase !== 'waiting'
      void this.load({ force: forceMarket })
    },

    setSearchQuery(query: string) {
      this.searchQuery = query
      this.page = 1
      void this.load()
    },

    setPage(page: number) {
      const nextPage = Math.max(1, page)
      if (this.page === nextPage) return
      this.page = nextPage
      void this.load()
    },

    async bootstrap() {
      if (this.bootstrapped) {
        await this.refresh()
        return
      }
      this.bootstrapped = true
      await this.load()
    },

    async refresh(options: { force?: boolean; silent?: boolean } = {}) {
      const force = options.force ?? false
      const silent = options.silent ?? !force
      if (
        !force &&
        this.lastRefreshedAt > 0 &&
        Date.now() - this.lastRefreshedAt < MIN_REFRESH_INTERVAL_MS
      ) {
        return
      }
      await this.load({ force, silent })
    },

    async load(options: { force?: boolean; silent?: boolean } = {}) {
      const silent = options.silent ?? false
      if (silent) {
        this.refreshing = true
      } else {
        this.loading = true
      }
      this.error = ''
      const offset = (this.page - 1) * this.pageSize
      const query = this.searchQuery.trim()
      const phase = this.data?.phase
      const isToday = this.tradeDate === todayTradeDate()
      const forceUpstream =
        Boolean(options.force) &&
        ((this.scope === 'market' && phase !== 'waiting') ||
          (!isToday && this.scope === 'top'))
      try {
        this.data = await fetchAuctionBoard(this.tradeDate, {
          sort: this.sort,
          scope: this.scope,
          q: query || undefined,
          offset,
          limit: this.pageSize,
          force: forceUpstream,
        })
        this.lastRefreshedAt = Date.now()
      } catch (error) {
        const raw = error instanceof Error ? error.message : '加载盘前竞价失败'
        this.error = raw.includes('502')
          ? '东财全市场暂不可用，请稍后重试或切换快速榜'
          : raw
        if (!silent && !this.data) {
          this.data = null
        }
      } finally {
        if (silent) {
          this.refreshing = false
        } else {
          this.loading = false
        }
      }
    },
  },
})
