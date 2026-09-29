import { defineStore } from 'pinia'

import { fetchMarketOverview } from '@/api/market'
import type { MarketOverview } from '@/types/api'

export const useMarketStore = defineStore('market', {
  state: () => ({
    tradeDate: new Date().toISOString().slice(0, 10),
    overview: null as MarketOverview | null,
    overviewByDate: {} as Record<string, MarketOverview>,
    loading: false,
    error: '' as string,
  }),
  getters: {
    overviewFor(state): (tradeDate: string) => MarketOverview | null {
      return (tradeDate: string) => state.overviewByDate[tradeDate] ?? null
    },
  },
  actions: {
    async ensureOverview(
      tradeDate: string,
      opts?: { force?: boolean },
    ): Promise<MarketOverview | null> {
      this.tradeDate = tradeDate
      if (!opts?.force) {
        const cached = this.overviewByDate[tradeDate]
        if (cached) {
          this.overview = cached
          return cached
        }
      }
      await this.loadOverview()
      if (this.overview) {
        this.overviewByDate[tradeDate] = this.overview
      }
      return this.overview
    },
    async loadOverview() {
      this.loading = true
      this.error = ''
      try {
        this.overview = await fetchMarketOverview(this.tradeDate)
        if (this.overview) {
          this.overviewByDate[this.tradeDate] = this.overview
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
  },
})
