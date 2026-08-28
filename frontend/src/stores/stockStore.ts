import { defineStore } from 'pinia'

import {
  fetchStockBars,
  fetchStockDetail,
  fetchStockFundFlow,
  fetchStockSectors,
  type StockBarsPayload,
  type StockDetail,
  type StockSectorItem,
} from '@/api/stocks'
import type { SectorFundFlowPayload } from '@/api/sectors'

export const useStockStore = defineStore('stock', {
  state: () => ({
    selectedSymbol: '' as string,
    detail: null as StockDetail | null,
    fundFlow: null as (SectorFundFlowPayload & { symbol: string }) | null,
    bars: null as StockBarsPayload | null,
    sectors: [] as StockSectorItem[],
    loading: false,
    error: '' as string,
    barsError: '' as string,
    fundError: '' as string,
  }),
  actions: {
    async loadBars(symbol: string, period: StockBarsPayload['period'] = 'day') {
      this.selectedSymbol = symbol
      this.barsError = ''
      try {
        this.bars = await fetchStockBars(symbol, period, 60)
      } catch (error) {
        this.bars = null
        this.barsError = error instanceof Error ? error.message : String(error)
      }
    },
    async loadAll(symbol: string, tradeDate: string) {
      this.selectedSymbol = symbol
      this.loading = true
      this.error = ''
      this.barsError = ''
      this.fundError = ''
      try {
        try {
          const [detail, sectors] = await Promise.all([
            fetchStockDetail(symbol),
            fetchStockSectors(symbol),
          ])
          this.detail = detail
          this.sectors = sectors.items
        } catch (error) {
          this.detail = null
          this.fundFlow = null
          this.bars = null
          this.sectors = []
          this.error = error instanceof Error ? error.message : String(error)
          return
        }

        try {
          this.fundFlow = await fetchStockFundFlow(symbol, tradeDate)
        } catch (error) {
          this.fundFlow = null
          this.fundError = error instanceof Error ? error.message : String(error)
        }

        try {
          this.bars = await fetchStockBars(symbol, 'day', 60)
        } catch (error) {
          this.bars = null
          this.barsError = error instanceof Error ? error.message : String(error)
        }
      } finally {
        this.loading = false
      }
    },
  },
})
