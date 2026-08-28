/** A-share intraday minute buckets: 09:30–11:30, 13:00–15:00 */
export const TRADING_MINUTES: string[] = (() => {
  const out: string[] = []
  for (let hm = 9 * 60 + 30; hm <= 11 * 60 + 30; hm++) {
    const hh = Math.floor(hm / 60)
    const mm = hm % 60
    out.push(`${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`)
  }
  for (let hm = 13 * 60; hm <= 15 * 60; hm++) {
    const hh = Math.floor(hm / 60)
    const mm = hm % 60
    out.push(`${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`)
  }
  return out
})()

export const X_AXIS_TICKS = ['09:30', '10:30', '11:30', '14:00', '15:00']

export function alignValuesToTradingMinutes(
  sourceTimeline: string[],
  values: (number | null)[],
): (number | null)[] {
  const map: Record<string, number | null> = {}
  let lastActualMinute: string | null = null
  sourceTimeline.forEach((t, i) => {
    const v = values[i] ?? null
    map[t] = v
    if (v != null) lastActualMinute = t
  })

  let last: number | null = null
  return TRADING_MINUTES.map((t) => {
    if (lastActualMinute == null || t > lastActualMinute) return null
    if (t in map && map[t] != null) {
      last = map[t]
      return last
    }
    return last
  })
}

/** Hide synthetic 15:00 and future replay minutes while today's session is open. */
export function filterLiveReplayMinutes(minutes: string[], tradeDate: string, now = new Date()): string[] {
  const today = now.toISOString().slice(0, 10)
  if (tradeDate !== today) return minutes
  const clock = currentTradingClockMinute(now)
  if (clock >= '15:00') return minutes
  return minutes.filter((minute) => minute !== '15:00' && minute <= clock)
}

export function capLiveReplayMinute(minute: string | null | undefined, tradeDate: string, now = new Date()): string | null {
  if (!minute) return null
  const filtered = filterLiveReplayMinutes([minute], tradeDate, now)
  return filtered[0] ?? null
}

export function countNonNullValues(values: (number | null)[] | undefined): number {
  return (values || []).filter((v) => v != null).length
}

export function currentTradingClockMinute(now = new Date()): string {
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

/** Drop synthetic 15:00 and future minutes while the session is still open. */
export function withoutPrematureClosingPoint<T extends { minute: string }>(points: T[], now = new Date()): T[] {
  const clock = currentTradingClockMinute(now)
  if (clock >= '15:00') return points
  return points.filter((point) => point.minute !== '15:00' && point.minute <= clock)
}
