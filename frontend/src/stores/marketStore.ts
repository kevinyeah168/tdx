import { defineStore } from 'pinia'

import { fetchMarketOverview } from '@/api/market'
import type { MarketOverview } from '@/types/api'

export const useMarketStore = defineStore('market', {
  state: () => ({
    tradeDate: new Date().toISOString().slice(0, 10),
    overview: null as MarketOverview | null,
    loading: false,
    error: '' as string,
  }),
  actions: {
    async loadOverview() {
      this.loading = true
      this.error = ''
      try {
        this.overview = await fetchMarketOverview(this.tradeDate)
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
  },
})
