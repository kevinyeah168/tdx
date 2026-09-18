import { isWeekdayDate } from '@/utils/tradingSession'
import { todayTradeDate } from '@/utils/tradeDate'

export type CycleReplayRangePresetKey = '1w' | '15d' | '1m' | '3m' | '6m' | '1y'

export interface CycleReplayRangePreset {
  key: CycleReplayRangePresetKey
  label: string
  /** Max trading days with hot data to include. */
  tradingDayLimit: number
  /** Minimum hot trading days required before the preset is enabled. */
  minAvailableDays: number
}

export const CYCLE_REPLAY_RANGE_PRESETS: CycleReplayRangePreset[] = [
  { key: '1w', label: '近一周', tradingDayLimit: 5, minAvailableDays: 1 },
  { key: '15d', label: '近15日', tradingDayLimit: 15, minAvailableDays: 2 },
  { key: '1m', label: '近一月', tradingDayLimit: 22, minAvailableDays: 5 },
  { key: '3m', label: '近三月', tradingDayLimit: 66, minAvailableDays: 20 },
  { key: '6m', label: '近半年', tradingDayLimit: 130, minAvailableDays: 60 },
  { key: '1y', label: '近一年', tradingDayLimit: 250, minAvailableDays: 120 },
]

export function sortedAvailableDates(availableDates: string[]): string[] {
  return [...availableDates].filter((date) => isWeekdayDate(date)).sort((a, b) => a.localeCompare(b))
}

export function normalizeRange(from: string, to: string): { from: string; to: string } {
  if (from <= to) return { from, to }
  return { from: to, to: from }
}

/** Latest date we can use as range end (prefer last day with hot data). */
export function resolveRangeEndDate(availableDates: string[]): string {
  const sorted = sortedAvailableDates(availableDates)
  if (sorted.length) return sorted[sorted.length - 1]!
  return todayTradeDate()
}

/**
 * Pick the last N trading days that actually exist in hot storage.
 * When the library has fewer days than the preset asks for, use all available days.
 */
export function presetAvailableRange(
  preset: CycleReplayRangePreset,
  availableDates: string[],
): { from: string; to: string } | null {
  const sorted = sortedAvailableDates(availableDates)
  if (!sorted.length) return null

  const take = Math.min(preset.tradingDayLimit, sorted.length)
  const slice = sorted.slice(-take)
  return {
    from: slice[0]!,
    to: slice[slice.length - 1]!,
  }
}

export function isPresetDisabled(
  preset: CycleReplayRangePreset,
  availableCount: number,
): boolean {
  return availableCount < preset.minAvailableDays
}

/**
 * Trading days inside [from, to] that exist in hot storage.
 */
export function tradingDatesInRange(
  from: string,
  to: string,
  availableDates: string[],
): string[] {
  const { from: start, to: end } = normalizeRange(from, to)
  const available = new Set(sortedAvailableDates(availableDates))

  return [...available]
    .filter((date) => date >= start && date <= end)
    .sort((a, b) => a.localeCompare(b))
}

export function clampRangeToAvailable(
  from: string,
  to: string,
  availableDates: string[],
): {
  from: string
  to: string
  timeline: string[]
  trimmed: boolean
} {
  const { from: requestedFrom, to: requestedTo } = normalizeRange(from, to)
  const timeline = tradingDatesInRange(requestedFrom, requestedTo, availableDates)

  if (!timeline.length) {
    return { from: requestedFrom, to: requestedTo, timeline, trimmed: false }
  }

  const effectiveFrom = timeline[0]!
  const effectiveTo = timeline[timeline.length - 1]!
  return {
    from: effectiveFrom,
    to: effectiveTo,
    timeline,
    trimmed: effectiveFrom !== requestedFrom || effectiveTo !== requestedTo,
  }
}

export function formatRangeLabel(from: string, to: string): string {
  const { from: start, to: end } = normalizeRange(from, to)
  if (start === end) return start
  return `${start} ~ ${end}`
}

export function formatAvailableDatesSummary(availableDates: string[]): string {
  const sorted = sortedAvailableDates(availableDates)
  if (!sorted.length) return '库内暂无可回放交易日'
  if (sorted.length <= 5) {
    return `库内可回放 ${sorted.length} 个交易日：${sorted.join('、')}`
  }
  return `库内可回放 ${sorted.length} 个交易日：${sorted[0]} ~ ${sorted[sorted.length - 1]}`
}

export function formatTrimmedRangeHint(
  requestedFrom: string,
  requestedTo: string,
  effectiveFrom: string,
  effectiveTo: string,
  timelineLength: number,
): string {
  const requested = formatRangeLabel(requestedFrom, requestedTo)
  const effective = formatRangeLabel(effectiveFrom, effectiveTo)
  return `所选区间 ${requested} 仅 ${timelineLength} 天有数据，已使用 ${effective}`
}
