import { describe, expect, it } from 'vitest'

import { movingAverage, rsi } from '@/utils/indicators'

describe('indicators', () => {
  it('computes moving average without NaN', () => {
    const values = [1, 2, 3, 4, 5]
    expect(movingAverage(values, 3)).toEqual([null, null, 2, 3, 4])
  })

  it('computes rsi for stable series', () => {
    const values = Array.from({ length: 20 }, (_, index) => 10 + index * 0.1)
    const result = rsi(values, 14)
    expect(result.at(-1)).toBeGreaterThan(50)
  })
})
