import { describe, expect, it } from 'vitest'

import { computeAvgPriceValues } from '@/utils/avgPrice'

describe('computeAvgPriceValues', () => {
  it('computes VWAP when amount deltas are available', () => {
    const closes = [10, 11, 12]
    const amountDeltas = [1000, 1100, 1200]
    expect(computeAvgPriceValues(closes, amountDeltas)).toEqual([10, 10.5, 11])
  })

  it('falls back to time-weighted close average when amount deltas are zero', () => {
    const closes = [10, 12, 11]
    const amountDeltas = [0, 0, 0]
    expect(computeAvgPriceValues(closes, amountDeltas)).toEqual([10, 11, 11])
  })
})
