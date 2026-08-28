import { defineStore } from 'pinia'

import {
  fetchSectorBreadth,
  fetchSectorFundFlow,
  fetchSectorMembers,
  fetchSectors,
  type SectorBreadthResponse,
  type SectorFundFlowPayload,
  type SectorMemberRankItem,
} from '@/api/sectors'
import { fetchReplayMinutes } from '@/api/replay'
import type { SectorSummary } from '@/types/api'
import { todayTradeDate } from '@/utils/tradeDate'

export type SectorTypeFilter = 'all' | 'industry' | 'concept'

export const useSectorStore = defineStore('sector', {
  state: () => ({
    items: [] as SectorSummary[],
    selectedId: '' as string,
    typeFilter: 'all' as SectorTypeFilter,
    searchQuery: '' as string,
    tradeDate: todayTradeDate(),
    replayMinute: '09:31' as string,
    hasSessionData: false,
    fundFlow: null as SectorFundFlowPayload | null,
    breadth: null as SectorBreadthResponse | null,
    memberRanks: [] as SectorMemberRankItem[],
    loading: false,
    fundLoading: false,
    membersLoading: false,
    error: '' as string,
    fundError: '' as string,
  }),
  getters: {
    selected(state): SectorSummary | null {
      return state.items.find((item) => item.sector_id === state.selectedId) ?? null
    },
    filteredItems(state): SectorSummary[] {
      const q = state.searchQuery.trim().toLowerCase()
      return state.items.filter((item) => {
        if (state.typeFilter === 'industry' && item.sector_type !== 'industry') return false
        if (state.typeFilter === 'concept' && item.sector_type !== 'concept') return false
        if (!q) return true
        return item.name.toLowerCase().includes(q) || item.sector_id.includes(q)
      })
    },
    latestMainFlow(state): number | null {
      const points = state.fundFlow?.points ?? []
      if (!points.length) return null
      const last = points[points.length - 1]!
      return last.values.main?.cumulative ?? null
    },
  },
  actions: {
    clearSessionData() {
      this.hasSessionData = false
      this.fundFlow = null
      this.breadth = null
      this.memberRanks = []
      this.fundError = ''
    },
    async bootstrap() {
      this.loading = true
      this.error = ''
      try {
        this.tradeDate = todayTradeDate()
        const response = await fetchSectors()
        this.items = response.items
        if (!this.selectedId && this.items.length > 0) {
          const preferred = this.items.find((item) => item.name.includes('5G')) ?? this.items[0]!
          this.selectedId = preferred.sector_id
        }
        await this.resolveSessionForDate(this.tradeDate)
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
    async resolveSessionForDate(tradeDate: string) {
      this.tradeDate = tradeDate
      try {
        const minutes = await fetchReplayMinutes(tradeDate)
        this.replayMinute = minutes.latest_complete_minute || minutes.minutes[minutes.minutes.length - 1] || '09:31'
        this.hasSessionData = minutes.minutes.length > 0
      } catch {
        this.clearSessionData()
        return
      }
      if (this.hasSessionData && this.selectedId) {
        await this.loadSelectedSectorData()
      } else {
        this.clearSessionData()
      }
    },
    setTradeDate(tradeDate: string, minute?: string) {
      const dateChanged = tradeDate !== this.tradeDate
      if (minute) this.replayMinute = minute
      if (dateChanged) {
        void this.resolveSessionForDate(tradeDate)
        return
      }
      if (this.hasSessionData && this.selectedId) {
        void this.reloadSnapshot()
      }
    },
    async reloadSnapshot() {
      if (!this.selectedId || !this.hasSessionData) return
      await Promise.all([this.loadMemberRanks(), this.loadBreadth()])
    },
    async reloadForDate() {
      await this.resolveSessionForDate(this.tradeDate)
    },
    selectSector(sectorId: string) {
      if (this.selectedId === sectorId) return
      this.selectedId = sectorId
      if (this.hasSessionData) {
        void this.loadSelectedSectorData()
      }
    },
    async loadSelectedSectorData() {
      if (!this.selectedId || !this.hasSessionData) return
      await this.loadFundFlow()
      await Promise.all([this.loadMemberRanks(), this.loadBreadth()])
    },
    async loadFundFlow() {
      if (!this.selectedId) return
      this.fundLoading = true
      this.fundError = ''
      try {
        this.fundFlow = await fetchSectorFundFlow(this.selectedId, this.tradeDate)
        if (this.fundFlow.latest_complete_minute) {
          this.replayMinute = this.fundFlow.latest_complete_minute
        }
      } catch (error) {
        this.fundFlow = null
        this.fundError = error instanceof Error ? error.message : String(error)
      } finally {
        this.fundLoading = false
      }
    },
    async loadMemberRanks() {
      if (!this.selectedId) return
      this.membersLoading = true
      try {
        const minute = this.fundFlow?.latest_complete_minute || this.replayMinute
        const members = await fetchSectorMembers(this.selectedId, this.tradeDate, minute, 100)
        this.memberRanks = members.items
      } catch {
        this.memberRanks = []
      } finally {
        this.membersLoading = false
      }
    },
    async loadBreadth() {
      if (!this.selectedId) return
      try {
        const minute = this.fundFlow?.latest_complete_minute || this.replayMinute
        this.breadth = await fetchSectorBreadth(this.selectedId, this.tradeDate, minute)
      } catch {
        this.breadth = null
      }
    },
  },
})
