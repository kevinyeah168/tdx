import { defineStore } from 'pinia'

import {
  fetchAuctionBoard,
  type AuctionBoardResponse,
  type AuctionBoardSort,
} from '@/api/auctionBoard'
import { AUCTION_POLL_MS } from '@/constants/refresh'
import { todayTradeDate } from '@/utils/tradeDate'

const MIN_REFRESH_INTERVAL_MS = AUCTION_POLL_MS

export const useAuctionBoardStore = defineStore('auctionBoard', {
  state: () => ({
    tradeDate: todayTradeDate(),
    sort: 'ratio' as AuctionBoardSort,
    data: null as AuctionBoardResponse | null,
    loading: false,
    error: '',
    bootstrapped: false,
    lastRefreshedAt: 0,
  }),

  getters: {
    isToday: (state) => state.tradeDate === todayTradeDate(),
    isSnapshot: (state) => state.data?.data_kind === 'snapshot',
    shouldPoll: (state) => {
      const phase = state.data?.phase
      return state.tradeDate === todayTradeDate() && (phase === 'auction' || phase === 'post_auction')
    },
  },

  actions: {
    setTradeDate(tradeDate: string) {
      if (this.tradeDate === tradeDate) return
      this.tradeDate = tradeDate
      void this.load({ force: true })
    },

    setSort(sort: AuctionBoardSort) {
      if (this.sort === sort) return
      this.sort = sort
      void this.load({ force: true })
    },

    async bootstrap() {
      if (this.bootstrapped) {
        await this.refresh()
        return
      }
      this.bootstrapped = true
      await this.load({ force: true })
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
      await this.load({ force })
    },

    async load(options: { force?: boolean } = {}) {
      this.loading = true
      this.error = ''
      try {
        this.data = await fetchAuctionBoard(this.tradeDate, {
          sort: this.sort,
          force: options.force,
        })
        this.lastRefreshedAt = Date.now()
      } catch (error) {
        this.error = error instanceof Error ? error.message : '加载盘前竞价失败'
        this.data = null
      } finally {
        this.loading = false
      }
    },
  },
})
