function computeTimeWeightedAvgPrice(closes: (number | null)[]): (number | null)[] {
  let sum = 0
  let count = 0
  return closes.map((close) => {
    if (close == null || !Number.isFinite(close) || close <= 0) {
      return count > 0 ? sum / count : null
    }
    sum += close
    count += 1
    return sum / count
  })
}

/** Session VWAP from minute amount deltas; falls back to time-weighted close average when amount is unavailable. */
export function computeAvgPriceValues(
  closes: (number | null)[],
  amountDeltas: (number | null)[],
): (number | null)[] {
  let cumAmount = 0
  let cumVolume = 0
  const vwap = closes.map((close, index) => {
    const amountDelta = amountDeltas[index]
    if (close != null && close > 0 && amountDelta != null && amountDelta > 0) {
      cumAmount += amountDelta
      cumVolume += amountDelta / close
    }
    if (cumVolume <= 0) return null
    return cumAmount / cumVolume
  })

  if (vwap.some((value) => value != null)) return vwap
  return computeTimeWeightedAvgPrice(closes)
}
