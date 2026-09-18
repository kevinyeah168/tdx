import { defineStore } from 'pinia'

import { fetchReplayDates } from '@/api/replay'
import { fetchSectorFundFlowBatch } from '@/api/sectors'
import { fetchSectorGroups, MAX_GROUP_MEMBERS } from '@/api/sectorGroups'
import { fetchStockFundFlowBatch } from '@/api/stocks'
import { fetchStockGroups } from '@/api/stockGroups'
import type { FlowSeries } from '@/types/board'
import {
  CYCLE_REPLAY_RANGE_PRESETS,
  clampRangeToAvailable,
  formatAvailableDatesSummary,
  formatRangeLabel,
  formatTrimmedRangeHint,
  isPresetDisabled,
  presetAvailableRange,
  sortedAvailableDates,
  type CycleReplayRangePresetKey,
} from '@/utils/cycleReplayRange'
import { buildRangeFlowSeries, endOfDayMainCumulative } from '@/utils/cycleReplaySeries'
import { inferSectorTypeFromId } from '@/utils/format'
import { isWeekdayDate } from '@/utils/tradingSession'
import { todayTradeDate } from '@/utils/tradeDate'

export const MAX_CYCLE_SECTOR = MAX_GROUP_MEMBERS
export const MAX_CYCLE_STOCK = 60

const PLAY_INTERVAL_MS = 1200
const RANGE_LOAD_CONCURRENCY = 4

export interface CycleReplayEntity {
  id: string
  name: string
}

export type CycleReplayEntityMode = 'sector' | 'stock'
export type CycleReplaySpeed = 1 | 2 | 4

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  if (!items.length) return []
  const results: R[] = new Array(items.length)
  let cursor = 0

  async function runNext(): Promise<void> {
    while (cursor < items.length) {
      const index = cursor
      cursor += 1
      results[index] = await worker(items[index]!, index)
    }
  }

  const runners = Array.from({ length: Math.min(concurrency, items.length) }, () => runNext())
  await Promise.all(runners)
  return results
}

export const useCycleReplayStore = defineStore('cycleReplay', {
  state: () => ({
    entityMode: 'sector' as CycleReplayEntityMode,
    dateFrom: todayTradeDate(),
    dateTo: todayTradeDate(),
    activePreset: '1m' as CycleReplayRangePresetKey | null,
    dateTimeline: [] as string[],
    sectorSelected: [] as CycleReplayEntity[],
    stockSelected: [] as CycleReplayEntity[],
    sourceGroupId: null as string | null,
    fullSeries: [] as FlowSeries[],
    frames: [] as string[],
    frameIndex: 0,
    playing: false,
    speed: 1 as CycleReplaySpeed,
    loading: false,
    error: '' as string,
    availableDates: [] as string[],
    requestedDateFrom: todayTradeDate(),
    requestedDateTo: todayTradeDate(),
    rangeStatusHint: '' as string,
    playTimer: null as ReturnType<typeof setInterval> | null,
  }),
  getters: {
    availableDateCount(state): number {
      return sortedAvailableDates(state.availableDates).length
    },
    availableSummary(state): string {
      return formatAvailableDatesSummary(state.availableDates)
    },
    presetDisabled(state) {
      return (key: CycleReplayRangePresetKey): boolean => {
        const preset = CYCLE_REPLAY_RANGE_PRESETS.find((item) => item.key === key)
        if (!preset) return true
        return isPresetDisabled(preset, sortedAvailableDates(state.availableDates).length)
      }
    },
    selected(state): CycleReplayEntity[] {
      return state.entityMode === 'sector' ? state.sectorSelected : state.stockSelected
    },
    maxSelected(): number {
      return this.entityMode === 'sector' ? MAX_CYCLE_SECTOR : MAX_CYCLE_STOCK
    },
    rangeLabel(state): string {
      return formatRangeLabel(state.dateFrom, state.dateTo)
    },
    cursorDate(state): string {
      return state.frames[state.frameIndex] ?? state.frames[state.frames.length - 1] ?? '—'
    },
    displayTimeline(state): string[] {
      return state.dateTimeline
    },
    displaySeries(state): FlowSeries[] {
      return state.fullSeries
    },
    frameLabel(state): string {
      if (!state.frames.length) return '—'
      return `${state.frameIndex + 1} / ${state.frames.length}`
    },
    progressPercent(state): number {
      if (state.frames.length <= 1) return 0
      return Math.round((state.frameIndex / (state.frames.length - 1)) * 100)
    },
  },
  actions: {
    stopTimer() {
      if (this.playTimer) {
        clearInterval(this.playTimer)
        this.playTimer = null
      }
      this.playing = false
    },

    async loadAvailableDates() {
      try {
        const response = await fetchReplayDates()
        const dates = new Set(response.dates.filter((date) => isWeekdayDate(date)))
        const today = todayTradeDate()
        if (isWeekdayDate(today)) dates.add(today)
        this.availableDates = [...dates].sort((a, b) => b.localeCompare(a))
      } catch {
        this.availableDates = isWeekdayDate(todayTradeDate()) ? [todayTradeDate()] : []
      }
    },

    initializeRange() {
      const count = sortedAvailableDates(this.availableDates).length
      if (!count) return

      const preferred = CYCLE_REPLAY_RANGE_PRESETS.find((preset) => preset.key === '1m')
      if (preferred && !isPresetDisabled(preferred, count)) {
        this.applyPreset('1m')
        return
      }

      const fallback = CYCLE_REPLAY_RANGE_PRESETS.find(
        (preset) => !isPresetDisabled(preset, count),
      )
      if (fallback) {
        this.applyPreset(fallback.key)
        return
      }

      const range = presetAvailableRange(CYCLE_REPLAY_RANGE_PRESETS[0]!, this.availableDates)
      if (!range) return
      this.activePreset = '1w'
      this.requestedDateFrom = range.from
      this.requestedDateTo = range.to
      this.dateFrom = range.from
      this.dateTo = range.to
      void this.reload()
    },

    applyPreset(key: CycleReplayRangePresetKey) {
      const preset = CYCLE_REPLAY_RANGE_PRESETS.find((item) => item.key === key)
      if (!preset || isPresetDisabled(preset, sortedAvailableDates(this.availableDates).length)) {
        return
      }

      const range = presetAvailableRange(preset, this.availableDates)
      if (!range) return

      this.activePreset = key
      this.requestedDateFrom = range.from
      this.requestedDateTo = range.to
      this.dateFrom = range.from
      this.dateTo = range.to
      this.stopTimer()
      this.frameIndex = 0
      void this.reload()
    },

    async setDateRange(from: string, to: string) {
      this.requestedDateFrom = from
      this.requestedDateTo = to
      this.dateFrom = from
      this.dateTo = to
      this.activePreset = null
      this.stopTimer()
      this.frameIndex = 0
      await this.reload()
    },

    setEntityMode(mode: CycleReplayEntityMode) {
      if (this.entityMode === mode) return
      this.stopTimer()
      this.entityMode = mode
      this.sourceGroupId = null
      this.frameIndex = 0
      void this.reload()
    },

    setSelected(entities: CycleReplayEntity[], sourceGroupId: string | null = null) {
      const capped = entities.slice(0, this.maxSelected)
      if (this.entityMode === 'sector') {
        this.sectorSelected = capped
      } else {
        this.stockSelected = capped
      }
      this.sourceGroupId = sourceGroupId
      this.stopTimer()
      this.frameIndex = 0
      void this.reload()
    },

    addEntities(entities: CycleReplayEntity[]) {
      const current = [...this.selected]
      const known = new Set(current.map((item) => item.id))
      for (const entity of entities) {
        if (known.has(entity.id)) continue
        if (current.length >= this.maxSelected) break
        current.push(entity)
        known.add(entity.id)
      }
      this.setSelected(current, null)
    },

    removeEntity(id: string) {
      const next = this.selected.filter((item) => item.id !== id)
      this.setSelected(next, this.sourceGroupId)
    },

    clearSelection() {
      this.setSelected([], null)
    },

    async applyGroup(groupId: string) {
      try {
        if (this.entityMode === 'sector') {
          const response = await fetchSectorGroups()
          const group = response.items.find((item) => item.id === groupId)
          if (!group) throw new Error('分组不存在')
          const entities = group.sectors
            .slice(0, MAX_CYCLE_SECTOR)
            .map((sector) => ({ id: sector.sector_id, name: sector.name }))
          this.setSelected(entities, group.id)
          return
        }

        const response = await fetchStockGroups()
        const group = response.items.find((item) => item.id === groupId)
        if (!group) throw new Error('分组不存在')
        const entities = group.symbols
          .slice(0, MAX_CYCLE_STOCK)
          .map((stock) => ({ id: stock.symbol, name: stock.name }))
        this.setSelected(entities, group.id)
      } catch (loadError) {
        this.error = loadError instanceof Error ? loadError.message : String(loadError)
      }
    },

    async reload() {
      this.stopTimer()
      this.error = ''
      this.rangeStatusHint = ''
      this.fullSeries = []
      this.frames = []
      this.dateTimeline = []
      this.frameIndex = 0

      const clamped = clampRangeToAvailable(
        this.requestedDateFrom,
        this.requestedDateTo,
        this.availableDates,
      )
      this.dateFrom = clamped.from
      this.dateTo = clamped.to
      this.dateTimeline = clamped.timeline
      this.frames = clamped.timeline

      if (!clamped.timeline.length) {
        this.error = `${formatRangeLabel(this.requestedDateFrom, this.requestedDateTo)} 区间内暂无 hot 数据`
        return
      }

      if (clamped.trimmed) {
        this.rangeStatusHint = formatTrimmedRangeHint(
          this.requestedDateFrom,
          this.requestedDateTo,
          clamped.from,
          clamped.to,
          clamped.timeline.length,
        )
      } else if (this.activePreset) {
        const preset = CYCLE_REPLAY_RANGE_PRESETS.find((item) => item.key === this.activePreset)
        if (preset && clamped.timeline.length < preset.tradingDayLimit) {
          this.rangeStatusHint = `库内仅 ${clamped.timeline.length} 天数据，已展示全部可用交易日`
        }
      }

      if (!this.selected.length) return

      const timeline = clamped.timeline

      this.loading = true
      try {
        const ids = this.selected.map((item) => item.id)
        const nameById = new Map(this.selected.map((item) => [item.id, item.name]))
        const valuesByEntity = new Map<string, Map<string, number | null>>(
          ids.map((id) => [id, new Map<string, number | null>()]),
        )

        await mapWithConcurrency(timeline, RANGE_LOAD_CONCURRENCY, async (tradeDate) => {
          if (this.entityMode === 'sector') {
            const batch = await fetchSectorFundFlowBatch(ids, tradeDate)
            for (const item of batch.items) {
              const cum = endOfDayMainCumulative(item.points)
              valuesByEntity.get(item.sector_id)?.set(tradeDate, cum)
            }
            return
          }

          const batch = await fetchStockFundFlowBatch(ids, tradeDate)
          for (const item of batch.items) {
            const cum = endOfDayMainCumulative(item.points)
            valuesByEntity.get(item.symbol)?.set(tradeDate, cum)
          }
        })

        const series: FlowSeries[] = []
        for (const id of ids) {
          const built = buildRangeFlowSeries(
            id,
            nameById.get(id) ?? id,
            timeline,
            valuesByEntity.get(id) ?? new Map(),
            this.entityMode === 'stock'
              ? { symbol: id }
              : { sector_type: inferSectorTypeFromId(id) },
          )
          if (built) series.push(built)
        }

        this.fullSeries = series
        if (!series.length) {
          this.error = `${this.rangeLabel} 所选标的暂无资金曲线`
        }
      } catch (loadError) {
        this.error = loadError instanceof Error ? loadError.message : String(loadError)
      } finally {
        this.loading = false
      }
    },

    seekFrame(index: number) {
      if (!this.frames.length) return
      const next = Math.max(0, Math.min(index, this.frames.length - 1))
      this.frameIndex = next
      if (next >= this.frames.length - 1) {
        this.stopTimer()
      }
    },

    togglePlay() {
      if (this.playing) {
        this.stopTimer()
        return
      }
      if (!this.frames.length || !this.fullSeries.length) return
      if (this.frameIndex >= this.frames.length - 1) {
        this.frameIndex = 0
      }
      this.playing = true
      this.playTimer = setInterval(() => {
        if (this.frameIndex >= this.frames.length - 1) {
          this.stopTimer()
          return
        }
        this.frameIndex += 1
      }, PLAY_INTERVAL_MS / this.speed)
    },

    setSpeed(speed: CycleReplaySpeed) {
      this.speed = speed
      if (this.playing) {
        this.stopTimer()
        this.togglePlay()
      }
    },

    stepPrev() {
      this.stopTimer()
      this.seekFrame(this.frameIndex - 1)
    },

    stepNext() {
      this.stopTimer()
      this.seekFrame(this.frameIndex + 1)
    },

    resetPlayback() {
      this.stopTimer()
      this.frameIndex = 0
    },
  },
})
