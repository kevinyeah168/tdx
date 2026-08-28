export function movingAverage(values: number[], period: number): (number | null)[] {
  if (period < 1) return values.map(() => null)
  return values.map((_, index) => {
    if (index + 1 < period) return null
    const window = values.slice(index + 1 - period, index + 1)
    return window.reduce((sum, value) => sum + value, 0) / period
  })
}

export function rsi(values: number[], period = 14): (number | null)[] {
  if (values.length <= period) return values.map(() => null)
  const out: (number | null)[] = Array(values.length).fill(null)
  let gains = 0
  let losses = 0
  for (let index = 1; index <= period; index += 1) {
    const delta = values[index] - values[index - 1]
    if (delta >= 0) gains += delta
    else losses -= delta
  }
  out[period] = 100 - 100 / (1 + gains / Math.max(losses, 1e-9))
  for (let index = period + 1; index < values.length; index += 1) {
    const delta = values[index] - values[index - 1]
    gains = (gains * (period - 1) + Math.max(delta, 0)) / period
    losses = (losses * (period - 1) + Math.max(-delta, 0)) / period
    out[index] = 100 - 100 / (1 + gains / Math.max(losses, 1e-9))
  }
  return out
}
