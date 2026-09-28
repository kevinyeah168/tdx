import { defineStore } from 'pinia'

import {
  addSectorGroupMembers,
  createSectorGroup,
  deleteSectorGroup,
  fetchSectorGroups,
  removeSectorGroupMember,
  renameSectorGroup,
  setActiveSectorGroup,
  type SectorGroup,
} from '@/api/sectorGroups'
import { fetchCustomSectors, type CustomSector } from '@/api/customSectors'
import {
  fetchSectorBreadth,
  fetchSectorFundFlow,
  fetchSectorMembers,
  fetchSectors,
  type SectorBreadthResponse,
  type SectorFundFlowPayload,
  type SectorMemberRankItem,
} from '@/api/sectors'
import { useMarketStore } from '@/stores/marketStore'
import { useReplayStore } from '@/stores/replayStore'
import { resolveLocalRankingMinute, shouldFetchCurvesForDate } from '@/utils/replayMinute'
import type { SectorSummary } from '@/types/api'
import { todayTradeDate } from '@/utils/tradeDate'

export type SectorTypeFilter = 'all' | 'industry' | 'concept'

function mapImportedSector(item: CustomSector): SectorSummary {
  return {
    sector_id: item.sector_id,
    name: item.name,
    sector_type: 'custom',
    member_count: item.members?.length ?? item.symbols?.length ?? 0,
  }
}

function importedSectorSignature(sectorIds: string[]): string {
  return sectorIds
    .map((id) => id.trim())
    .filter(Boolean)
    .sort()
    .join(',')
}

export const useSectorStore = defineStore('sector', {
  state: () => ({
    items: [] as SectorSummary[],
    importedItems: [] as SectorSummary[],
    cachedImportedSectorSignature: '' as string,
    selectedId: '' as string,
    typeFilter: 'all' as SectorTypeFilter,
    searchQuery: '' as string,
    groups: [] as SectorGroup[],
    activeGroupId: 'all' as string,
    groupsLoading: false,
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
      return (
        state.importedItems.find((item) => item.sector_id === state.selectedId) ??
        state.items.find((item) => item.sector_id === state.selectedId) ??
        null
      )
    },
    importedFilteredItems(state): SectorSummary[] {
      const q = state.searchQuery.trim().toLowerCase()
      if (!q) return state.importedItems
      return state.importedItems.filter(
        (item) => item.name.toLowerCase().includes(q) || item.sector_id.includes(q),
      )
    },
    activeGroup(state): SectorGroup | null {
      if (state.activeGroupId === 'all') return null
      return state.groups.find((group) => group.id === state.activeGroupId) ?? null
    },
    filteredItems(state): SectorSummary[] {
      const q = state.searchQuery.trim().toLowerCase()
      const importedIds = new Set(state.importedItems.map((item) => item.sector_id))
      let items = state.items.filter((item) => !importedIds.has(item.sector_id))
      if (state.activeGroupId !== 'all') {
        const group = state.groups.find((entry) => entry.id === state.activeGroupId)
        if (!group) return []
        const idSet = new Set(group.sector_ids)
        items = items.filter((item) => idSet.has(item.sector_id))
      } else {
        items = items.filter((item) => {
          if (state.typeFilter === 'industry' && item.sector_type !== 'industry') return false
          if (state.typeFilter === 'concept' && item.sector_type !== 'concept') return false
          return true
        })
      }
      if (!q) return items
      return items.filter(
        (item) => item.name.toLowerCase().includes(q) || item.sector_id.includes(q),
      )
    },
    latestMainFlow(state): number | null {
      const points = state.fundFlow?.points ?? []
      if (!points.length) return null
      const last = points[points.length - 1]!
      return last.values.main?.cumulative ?? null
    },
    visibleSidebarItems(): SectorSummary[] {
      return [...this.importedFilteredItems, ...this.filteredItems]
    },
  },
  actions: {
    replaceGroup(group: SectorGroup) {
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
        const response = await fetchSectorGroups()
        this.groups = response.items
        this.activeGroupId = response.active_group_id || 'all'
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.groupsLoading = false
      }
    },
    async setActiveGroup(groupId: string) {
      this.activeGroupId = await setActiveSectorGroup(groupId)
      const visible = this.visibleSidebarItems
      if (!visible.some((item) => item.sector_id === this.selectedId)) {
        const next = visible[0]
        if (next) {
          await this.selectSector(next.sector_id)
        }
      }
    },
    async createGroup(name: string) {
      const group = await createSectorGroup(name)
      this.replaceGroup(group)
      await this.setActiveGroup(group.id)
      return group
    },
    async renameGroup(groupId: string, name: string) {
      const group = await renameSectorGroup(groupId, name)
      this.replaceGroup(group)
    },
    async deleteGroup(groupId: string) {
      await deleteSectorGroup(groupId)
      this.groups = this.groups.filter((group) => group.id !== groupId)
      if (this.activeGroupId === groupId) {
        await this.setActiveGroup('all')
      }
    },
    async addSectorToGroup(groupId: string, sectorId: string) {
      const group = await addSectorGroupMembers(groupId, [sectorId])
      this.replaceGroup(group)
    },
    async removeSectorFromGroup(groupId: string, sectorId: string) {
      const group = await removeSectorGroupMember(groupId, sectorId)
      this.replaceGroup(group)
      if (this.activeGroupId === groupId && this.selectedId === sectorId) {
        const visible = this.visibleSidebarItems
        const next = visible[0]
        if (next) {
          await this.selectSector(next.sector_id)
        } else {
          this.selectedId = ''
        }
      }
    },
    clearSessionData() {
      this.hasSessionData = false
      this.fundFlow = null
      this.breadth = null
      this.memberRanks = []
      this.fundError = ''
    },
    async loadImportedSectors() {
      try {
        const { items } = await fetchCustomSectors()
        const directoryItems = items.filter((item) => item.source_type === 'directory')
        this.importedItems = directoryItems.map(mapImportedSector)
        this.cachedImportedSectorSignature = importedSectorSignature(
          directoryItems.map((item) => item.sector_id),
        )
      } catch {
        this.importedItems = []
        this.cachedImportedSectorSignature = ''
      }
    },
    async refreshImportedSectorsIfChanged() {
      try {
        const { items } = await fetchCustomSectors()
        const signature = importedSectorSignature(
          items.filter((item) => item.source_type === 'directory').map((item) => item.sector_id),
        )
        if (signature === this.cachedImportedSectorSignature) return
        await this.loadImportedSectors()
        const visible = this.visibleSidebarItems
        if (this.selectedId && !visible.some((item) => item.sector_id === this.selectedId)) {
          const next = visible[0]
          if (next) {
            await this.selectSector(next.sector_id)
          } else {
            this.selectedId = ''
          }
        }
      } catch {
        /* background refresh should not surface */
      }
    },
    async bootstrap() {
      this.loading = true
      this.error = ''
      try {
        this.tradeDate = todayTradeDate()
        const [sectorsResponse] = await Promise.all([
          fetchSectors(),
          this.loadGroups(),
          this.loadImportedSectors(),
        ])
        this.items = sectorsResponse.items
        if (!this.selectedId) {
          const visible = this.visibleSidebarItems
          const preferred =
            visible[0] ??
            this.items.find((item) => item.name.includes('煤炭')) ??
            this.items[0]
          if (preferred) {
            this.selectedId = preferred.sector_id
          }
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
      const marketStore = useMarketStore()
      const replayStore = useReplayStore()
      try {
        await marketStore.ensureOverview(tradeDate)
      } catch {
        /* optional */
      }
      const overview = marketStore.overviewFor(tradeDate)
      this.replayMinute = resolveLocalRankingMinute(tradeDate, { overview })
      this.hasSessionData = shouldFetchCurvesForDate(
        tradeDate,
        replayStore.availableDates,
        overview,
      )
      if (!this.selectedId) return
      try {
        await this.loadSelectedSectorData()
        this.hasSessionData = Boolean(this.fundFlow?.points?.length)
      } catch {
        this.hasSessionData = false
      }
      if (!this.hasSessionData) {
        this.clearSessionData()
      }
    },
    setTradeDate(tradeDate: string, minute?: string) {
      const dateChanged = tradeDate !== this.tradeDate
      if (minute) this.replayMinute = minute
      if (dateChanged || !this.hasSessionData) {
        void this.resolveSessionForDate(tradeDate)
        return
      }
      if (this.selectedId) {
        void this.reloadLiveData()
      }
    },
    async reloadSnapshot() {
      await this.reloadLiveData()
    },
    async reloadLiveData() {
      if (!this.selectedId || !this.hasSessionData) return
      await Promise.all([this.loadFundFlow(), this.loadMemberRanks(), this.loadBreadth()])
    },
    async reloadForDate() {
      await this.loadImportedSectors()
      await this.resolveSessionForDate(this.tradeDate)
    },
    async selectSector(sectorId: string) {
      if (this.selectedId === sectorId) return
      this.selectedId = sectorId
      if (!this.hasSessionData) {
        await this.resolveSessionForDate(this.tradeDate)
        return
      }
      await this.loadSelectedSectorData()
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
