import { defineStore } from 'pinia'

import { fetchLimitUpLadder, type LimitUpLadderResponse } from '@/api/limitUpLadder'
import { HOT_LIST_POLL_MS } from '@/constants/refresh'
import { todayTradeDate } from '@/utils/tradeDate'

const MIN_REFRESH_INTERVAL_MS = HOT_LIST_POLL_MS

export const useLimitUpLadderStore = defineStore('limitUpLadder', {
  state: () => ({
    tradeDate: todayTradeDate(),
    data: null as LimitUpLadderResponse | null,
    loading: false,
    error: '',
    bootstrapped: false,
    lastRefreshedAt: 0,
  }),

  getters: {
    isToday: (state) => state.tradeDate === todayTradeDate(),
    isSnapshot: (state) => state.data?.data_kind === 'snapshot',
  },

  actions: {
    setTradeDate(tradeDate: string) {
      if (this.tradeDate === tradeDate) return
      this.tradeDate = tradeDate
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
        this.data = await fetchLimitUpLadder(this.tradeDate, { force: options.force })
        this.lastRefreshedAt = Date.now()
      } catch (error) {
        this.error = error instanceof Error ? error.message : '加载涨停梯队失败'
        this.data = null
      } finally {
        this.loading = false
      }
    },
  },
})
