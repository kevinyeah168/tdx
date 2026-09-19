import { defineStore } from 'pinia'

import type { SectorFundFlowPayload } from '@/api/sectors'
import {
  addStockGroupMembers,
  createStockGroup,
  deleteStockGroup,
  fetchStockGroups,
  removeStockGroupMember,
  renameStockGroup,
  setActiveStockGroup,
  type StockGroup,
} from '@/api/stockGroups'
import {
  fetchStockCatalog,
  fetchStockFundFlowBatch,
  fetchStockGrayFlow,
  fetchStockGrayFlowBatch,
  fetchStockRank,
  type StockGrayFlowPayload,
} from '@/api/stocks'
import { isApiNotFound } from '@/api/client'
import type { FlowSeries } from '@/types/board'
import {
  attachGrayToSeries,
  buildStockFlowSeries,
  trimSeriesValuesToMinute,
} from '@/utils/stockSeries'
import { todayTradeDate } from '@/utils/tradeDate'

export const MAX_CHART_STOCKS = 60

export interface StockListItem {
  symbol: string
  name: string
  main_cumulative: number | null
  change_pct: number | null
}

interface StockSeriesContext {
  fundCache: Record<string, SectorFundFlowPayload & { symbol: string }>
  grayCache: Record<string, StockGrayFlowPayload>
  nameCache: Record<string, string>
  listItems: StockListItem[]
  replayMinute: string
}

function resolveStockSeries(
  ctx: StockSeriesContext,
  symbol: string,
  withGray = false,
): FlowSeries | null {
  const normalized = symbol.toUpperCase()
  const payload = ctx.fundCache[normalized]
  if (!payload) return null
  const name = ctx.nameCache[normalized] ?? symbol
  const listItem = ctx.listItems.find((item) => item.symbol === normalized)
  const built = buildStockFlowSeries(
    symbol,
    name,
    payload.points,
    listItem?.change_pct ?? null,
    ctx.replayMinute,
  )
  if (!built) return null
  if (withGray) {
    const gray = ctx.grayCache[normalized]
    if (gray?.points.length) {
      return attachGrayToSeries(built, gray.points, ctx.replayMinute)
    }
  }
  return built
}

export const useStockStore = defineStore('stock', {
  state: () => ({
    listItems: [] as StockListItem[],
    listMinute: '' as string,
    chartSymbols: [] as string[],
    highlightedSymbol: '' as string,
    soloSymbol: '' as string,
    fundCache: {} as Record<string, SectorFundFlowPayload & { symbol: string }>,
    grayCache: {} as Record<string, StockGrayFlowPayload>,
    nameCache: {} as Record<string, string>,
    tradeDate: todayTradeDate(),
    replayMinute: '09:31' as string,
    searchQuery: '' as string,
    groups: [] as StockGroup[],
    activeGroupId: 'all' as string,
    groupsLoading: false,
    listLoading: false,
    chartLoading: false,
    error: '' as string,
    chartError: '' as string,
    bootstrapped: false,
    listReloadTimer: null as ReturnType<typeof setTimeout> | null,
  }),
  getters: {
    activeGroup(state): StockGroup | null {
      if (state.activeGroupId === 'all') return null
      return state.groups.find((group) => group.id === state.activeGroupId) ?? null
    },
    filteredListItems(state): StockListItem[] {
      const q = state.searchQuery.trim().toLowerCase()
      const bySymbol = new Map(state.listItems.map((item) => [item.symbol, item]))
      let items: StockListItem[]

      if (state.activeGroupId === 'all') {
        items = state.listItems
      } else {
        const group = state.groups.find((entry) => entry.id === state.activeGroupId)
        if (!group) return []
        items = group.symbol_ids.map((symbol) => {
          const normalized = symbol.toUpperCase()
          const existing = bySymbol.get(normalized)
          if (existing) return existing
          const member = group.symbols.find((entry) => entry.symbol === normalized)
          return {
            symbol: normalized,
            name: member?.name ?? normalized,
            main_cumulative: null,
            change_pct: null,
          }
        })
      }

      if (q) {
        return items.filter(
          (item) =>
            item.symbol.toLowerCase().includes(q) ||
            item.name.toLowerCase().includes(q),
        )
      }

      return items.slice(0, MAX_CHART_STOCKS)
    },
    chartSeries(state): FlowSeries[] {
      const ctx: StockSeriesContext = {
        fundCache: state.fundCache,
        grayCache: state.grayCache,
        nameCache: state.nameCache,
        listItems: state.listItems,
        replayMinute: state.replayMinute,
      }
      return state.chartSymbols
        .map((symbol) => {
          const series = resolveStockSeries(ctx, symbol)
          return series ? trimSeriesValuesToMinute(series, state.replayMinute) : null
        })
        .filter((item): item is FlowSeries => item != null)
    },
    soloSeries(state): FlowSeries | null {
      if (!state.soloSymbol) return null
      const ctx: StockSeriesContext = {
        fundCache: state.fundCache,
        grayCache: state.grayCache,
        nameCache: state.nameCache,
        listItems: state.listItems,
        replayMinute: state.replayMinute,
      }
      const series = resolveStockSeries(ctx, state.soloSymbol, true)
      return series ? trimSeriesValuesToMinute(series, state.replayMinute) : null
    },
    isSoloMode(state): boolean {
      return Boolean(state.soloSymbol)
    },
    hasChartData(): boolean {
      return this.chartSeries.length > 0
    },
    selectedCount(state): number {
      return state.chartSymbols.length
    },
    chartSymbolSet(state): Set<string> {
      return new Set(state.chartSymbols)
    },
  },
  actions: {
    seriesContext(): StockSeriesContext {
      return {
        fundCache: this.fundCache,
        grayCache: this.grayCache,
        nameCache: this.nameCache,
        listItems: this.listItems,
        replayMinute: this.replayMinute,
      }
    },
    replaceGroup(group: StockGroup) {
      const index = this.groups.findIndex((entry) => entry.id === group.id)
      if (index >= 0) {
        this.groups.splice(index, 1, group)
      } else {
        this.groups.push(group)
      }
    },
    async loadGroups() {
      this.groupsLoading = true
      try {
        const response = await fetchStockGroups()
        this.groups = response.items
        this.activeGroupId = response.active_group_id || 'all'
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.groupsLoading = false
      }
    },
    async setActiveGroup(groupId: string) {
      if (this.activeGroupId === groupId) return
      this.activeGroupId = await setActiveStockGroup(groupId)
      this.searchQuery = ''
      this.applyGroupChartSelection()
    },
    applyGroupChartSelection() {
      this.soloSymbol = ''
      const symbols = this.filteredListItems
        .slice(0, MAX_CHART_STOCKS)
        .map((item) => item.symbol)
      this.chartSymbols = symbols
      this.highlightedSymbol = symbols[0] ?? ''
      this.chartError = ''
      void this.loadChartData()
    },
    async createGroup(name: string) {
      const group = await createStockGroup(name)
      this.replaceGroup(group)
      await this.setActiveGroup(group.id)
      return group
    },
    async renameGroup(groupId: string, name: string) {
      const group = await renameStockGroup(groupId, name)
      this.replaceGroup(group)
    },
    async deleteGroup(groupId: string) {
      await deleteStockGroup(groupId)
      this.groups = this.groups.filter((group) => group.id !== groupId)
      if (this.activeGroupId === groupId) {
        await this.setActiveGroup('all')
      }
    },
    async addSymbolToGroup(groupId: string, symbol: string) {
      await this.addSymbolsToGroup(groupId, [symbol])
    },
    async addSymbolsToGroup(groupId: string, symbols: string[]) {
      const normalized = [...new Set(symbols.map((symbol) => symbol.toUpperCase()).filter(Boolean))]
      if (!normalized.length) return
      const group = await addStockGroupMembers(groupId, normalized)
      this.replaceGroup(group)
      return group
    },
    async removeSymbolFromGroup(groupId: string, symbol: string) {
      const group = await removeStockGroupMember(groupId, symbol)
      this.replaceGroup(group)
    },
    setReplayContext(tradeDate: string, minute: string) {
      const dateChanged = this.tradeDate !== tradeDate
      const minuteChanged = this.replayMinute !== minute
      this.tradeDate = tradeDate
      this.replayMinute = minute
      if (dateChanged) {
        this.fundCache = {}
        this.grayCache = {}
        void this.reloadForDate()
        return
      }
      if (minuteChanged) {
        this.scheduleListReload()
      }
    },
    scheduleListReload() {
      if (this.listReloadTimer) clearTimeout(this.listReloadTimer)
      this.listReloadTimer = setTimeout(() => {
        this.listReloadTimer = null
        void this.loadMarketList()
      }, 350)
    },
    async loadMarketList() {
      this.listLoading = true
      this.error = ''
      try {
        const response = await fetchStockRank(this.tradeDate, this.replayMinute)
        this.listMinute = response.minute
        this.listItems = response.items.map((item) => ({
          symbol: item.symbol.toUpperCase(),
          name: item.name,
          main_cumulative: item.main_cumulative,
          change_pct: item.change_pct,
        }))
      } catch (error) {
        if (isApiNotFound(error)) {
          try {
            const catalog = await fetchStockCatalog()
            this.listMinute = this.replayMinute
            this.listItems = catalog.items.map((item) => ({
              symbol: item.symbol.toUpperCase(),
              name: item.name,
              main_cumulative: null,
              change_pct: null,
            }))
          } catch (catalogError) {
            this.error = catalogError instanceof Error ? catalogError.message : String(catalogError)
          }
        } else {
          this.error = error instanceof Error ? error.message : String(error)
        }
      } finally {
        for (const item of this.listItems) {
          this.nameCache[item.symbol] = item.name
        }
        this.listLoading = false
      }
    },
    async bootstrap(initialSymbol: string, tradeDate: string, minute: string) {
      const firstBoot = !this.bootstrapped
      this.tradeDate = tradeDate
      this.replayMinute = minute
      this.error = ''

      if (firstBoot) {
        await Promise.all([this.loadMarketList(), this.loadGroups()])
        if (initialSymbol) {
          this.selectForChart(initialSymbol, true)
          await this.loadChartData()
        } else {
          this.applyGroupChartSelection()
        }
      } else if (initialSymbol) {
        this.selectForChart(initialSymbol, true)
        await this.loadChartData()
      }

      this.bootstrapped = true
    },
    async enterSolo(symbol: string) {
      const normalized = symbol.toUpperCase()
      this.soloSymbol = normalized
      this.highlightedSymbol = normalized
      if (!this.chartSymbols.includes(normalized)) {
        this.selectForChart(normalized, true)
      }
      this.chartLoading = true
      try {
        await this.ensureSymbolData(normalized, true)
      } finally {
        this.chartLoading = false
      }
    },
    exitSolo() {
      this.soloSymbol = ''
    },
    async ensureSymbolData(symbol: string, withGray = false) {
      const normalized = symbol.toUpperCase()
      if (!this.fundCache[normalized]) {
        const batch = await fetchStockFundFlowBatch([normalized], this.tradeDate)
        for (const item of batch.items) {
          this.fundCache[item.symbol.toUpperCase()] = item
        }
      }
      if (withGray && !this.grayCache[normalized]) {
        try {
          this.grayCache[normalized] = await fetchStockGrayFlow(normalized, this.tradeDate)
        } catch {
          // gray optional
        }
      }
      this.syncListItemMetrics(normalized)
    },
    syncListItemMetrics(symbol: string) {
      const normalized = symbol.toUpperCase()
      const listItem = this.listItems.find((item) => item.symbol === normalized)
      const built = resolveStockSeries(this.seriesContext(), normalized)
      if (!listItem || !built) return
      listItem.main_cumulative = built.cum_main
      listItem.change_pct = built.change_pct ?? listItem.change_pct
    },
    focusSymbol(symbol: string) {
      this.highlightedSymbol = symbol.toUpperCase()
    },
    selectForChart(symbol: string, selected: boolean) {
      const normalized = symbol.toUpperCase()
      const exists = this.chartSymbols.includes(normalized)
      if (selected) {
        if (exists) return
        if (this.chartSymbols.length >= MAX_CHART_STOCKS) {
          this.chartError = `最多同时展示 ${MAX_CHART_STOCKS} 只个股曲线`
          return
        }
        this.chartSymbols.push(normalized)
        this.chartError = ''
        this.highlightedSymbol = normalized
        return
      }
      this.chartSymbols = this.chartSymbols.filter((item) => item !== normalized)
      if (this.soloSymbol === normalized) {
        this.exitSolo()
      }
      if (this.highlightedSymbol === normalized) {
        this.highlightedSymbol = this.chartSymbols[this.chartSymbols.length - 1] ?? ''
      }
    },
    addSymbol(symbol: string) {
      const normalized = symbol.toUpperCase()
      this.focusSymbol(normalized)
      this.selectForChart(normalized, true)
      return normalized
    },
    selectTop(count: number = MAX_CHART_STOCKS) {
      this.soloSymbol = ''
      const symbols = this.filteredListItems
        .slice()
        .sort((a, b) => Number(b.main_cumulative || 0) - Number(a.main_cumulative || 0))
        .slice(0, count)
        .map((item) => item.symbol)
      this.chartSymbols = symbols
      this.highlightedSymbol = symbols[0] ?? ''
      this.chartError = ''
      void this.loadChartData()
    },
    clearChartSelection() {
      this.chartSymbols = []
      this.highlightedSymbol = ''
      this.soloSymbol = ''
    },
    async loadChartData() {
      if (!this.chartSymbols.length && !this.soloSymbol) return
      this.chartLoading = true
      this.chartError = ''
      try {
        const targets = [...new Set([...this.chartSymbols, ...(this.soloSymbol ? [this.soloSymbol] : [])])]
        const missing = targets.filter((symbol) => !this.fundCache[symbol.toUpperCase()])
        if (missing.length) {
          const batch = await fetchStockFundFlowBatch(missing, this.tradeDate)
          for (const item of batch.items) {
            this.fundCache[item.symbol.toUpperCase()] = item
          }
        }
        if (this.soloSymbol && !this.grayCache[this.soloSymbol]) {
          try {
            const grayBatch = await fetchStockGrayFlowBatch([this.soloSymbol], this.tradeDate)
            for (const item of grayBatch.items) {
              this.grayCache[item.symbol.toUpperCase()] = item
            }
          } catch {
            // gray optional
          }
        }
        for (const symbol of targets) {
          this.syncListItemMetrics(symbol)
        }
      } catch (error) {
        this.chartError = error instanceof Error ? error.message : String(error)
      } finally {
        this.chartLoading = false
      }
    },
    async reloadForDate() {
      this.fundCache = {}
      this.grayCache = {}
      await this.loadMarketList()
      if (this.filteredListItems.length) {
        this.applyGroupChartSelection()
      } else {
        this.clearChartSelection()
      }
    },
  },
})
