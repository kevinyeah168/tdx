import type { MarketOverview } from '@/types/api'
import { isWeekdayDate, shouldFetchMarketDataForDate } from '@/utils/tradingSession'
import {
  TRADING_MINUTES,
  capLiveReplayMinute,
  currentTradingClockMinute,
  filterLiveReplayMinutes,
} from '@/utils/tradingTimeline'
import { todayTradeDate } from '@/utils/tradeDate'

function previousTradingMinute(minute: string): string | null {
  const index = TRADING_MINUTES.indexOf(minute)
  if (index <= 0) return null
  return TRADING_MINUTES[index - 1] ?? null
}

/** Fixed intraday axis for board curves; live today may hide future minutes. */
export function defaultBoardTimeline(tradeDate: string): string[] {
  const mins = filterLiveReplayMinutes([...TRADING_MINUTES], tradeDate)
  const first = mins[0]
  const prev = first ? previousTradingMinute(first) : null
  if (prev && !mins.includes(prev)) {
    return [prev, ...mins]
  }
  return mins
}

export function resolveLocalRankingMinute(
  tradeDate: string,
  opts?: {
    replayMinute?: string | null
    overview?: MarketOverview | null
  },
): string {
  const replayMinute = opts?.replayMinute
  const overview = opts?.overview
  if (!shouldFetchMarketDataForDate(tradeDate)) {
    return replayMinute ?? '09:31'
  }
  if (replayMinute) {
    return capLiveReplayMinute(replayMinute, tradeDate) ?? replayMinute
  }

  const fromOverview =
    overview?.latest_available_minute ??
    overview?.latest_complete_minute ??
    overview?.minute ??
    null
  const cappedOverview = capLiveReplayMinute(fromOverview, tradeDate)
  if (cappedOverview) return cappedOverview

  const calendarToday = todayTradeDate()
  if (tradeDate !== calendarToday) {
    return capLiveReplayMinute('15:00', tradeDate) ?? '15:00'
  }

  const clock = currentTradingClockMinute()
  if (clock < '09:30') return '09:31'
  return capLiveReplayMinute(clock, tradeDate) ?? clock
}

export function hasIntradaySamplesFromOverview(overview?: MarketOverview | null): boolean {
  return Boolean(overview?.latest_available_minute || overview?.latest_complete_minute)
}

export function shouldFetchCurvesForDate(
  tradeDate: string,
  replayDates: string[],
  overview?: MarketOverview | null,
  calendarToday = todayTradeDate(),
): boolean {
  if (replayDates.includes(tradeDate)) return true
  if (hasIntradaySamplesFromOverview(overview)) return true
  if (tradeDate === calendarToday && isWeekdayDate(tradeDate)) return true
  return false
}

export function syncReplayMinuteForDate(
  tradeDate: string,
  overview?: MarketOverview | null,
  opts?: { resetToLatest?: boolean; currentMinute?: string },
): string {
  const resolved = resolveLocalRankingMinute(tradeDate, {
    replayMinute: opts?.resetToLatest ? null : opts?.currentMinute,
    overview,
  })
  if (opts?.resetToLatest) return resolved
  if (opts?.currentMinute && TRADING_MINUTES.includes(opts.currentMinute)) {
    return capLiveReplayMinute(opts.currentMinute, tradeDate) ?? opts.currentMinute
  }
  return resolved
}
