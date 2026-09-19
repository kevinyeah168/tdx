import { todayTradeDate } from '@/utils/tradeDate'

export type MarketStatus =
  | 'pre_open'
  | 'open'
  | 'lunch_break'
  | 'closed'
  | 'non_trading_day'

/** A-share intraday sessions: 09:30–11:30, 13:00–15:00 (inclusive). */
const SESSION_WINDOWS: ReadonlyArray<readonly [number, number]> = [
  [9 * 60 + 30, 11 * 60 + 30],
  [13 * 60, 15 * 60],
]

export function isWeekdayDate(dateStr: string): boolean {
  const [year, month, day] = dateStr.split('-').map(Number)
  if (!year || !month || !day) return false
  const weekday = new Date(year, month - 1, day).getDay()
  return weekday >= 1 && weekday <= 5
}

/** Whether intraday/replay APIs should be called for this calendar date. */
export function shouldFetchMarketDataForDate(dateStr: string): boolean {
  return isWeekdayDate(dateStr)
}

function clockMinutes(now: Date): number {
  return now.getHours() * 60 + now.getMinutes()
}

/** Whether wall-clock is inside a live trading session (weekday + session window). */
export function isLiveTradingClock(now = new Date()): boolean {
  const weekday = now.getDay()
  if (weekday === 0 || weekday === 6) return false
  const minute = clockMinutes(now)
  return SESSION_WINDOWS.some(([start, end]) => minute >= start && minute <= end)
}

/** Market status for today's calendar view (or historical date on a weekday). */
export function resolveLiveMarketStatus(
  viewTradeDate: string,
  calendarToday = todayTradeDate(),
  now = new Date(),
): MarketStatus {
  if (!isWeekdayDate(viewTradeDate)) return 'non_trading_day'
  if (viewTradeDate !== calendarToday) return 'closed'

  if (!isWeekdayDate(calendarToday)) return 'non_trading_day'

  const minute = clockMinutes(now)
  if (minute < SESSION_WINDOWS[0][0]) return 'pre_open'
  if (minute <= SESSION_WINDOWS[0][1]) return 'open'
  if (minute < SESSION_WINDOWS[1][0]) return 'lunch_break'
  if (minute <= SESSION_WINDOWS[1][1]) return 'open'
  return 'closed'
}

export function shouldPollLiveWorkbench(opts: {
  mode: 'live' | 'replay'
  tradeDate: string
  calendarToday?: string
  now?: Date
}): boolean {
  if (opts.mode !== 'live') return false
  const today = opts.calendarToday ?? todayTradeDate()
  if (opts.tradeDate !== today) return false
  return isLiveTradingClock(opts.now)
}
