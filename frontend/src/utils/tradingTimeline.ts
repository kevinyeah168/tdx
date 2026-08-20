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
  let lastSampledTime: string | null = null
  sourceTimeline.forEach((t, i) => {
    const v = values[i] ?? null
    map[t] = v
    // Keep the latest minute that actually has a captured sample
    if (v != null) lastSampledTime = t
  })

  let last: number | null = null
  return TRADING_MINUTES.map((t) => {
    // Fixed full-day X axis, but do not extend the line past latest sample
    if (lastSampledTime == null || t > lastSampledTime) return null
    if (t in map && map[t] != null) last = map[t]
    return last
  })
}

export function countNonNullValues(values: (number | null)[] | undefined): number {
  return (values || []).filter((v) => v != null).length
}
