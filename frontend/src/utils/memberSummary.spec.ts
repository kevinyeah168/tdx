import { describe, expect, it } from 'vitest'

import { summarizeMemberNames } from './memberSummary'

describe('summarizeMemberNames', () => {
  it('joins short lists', () => {
    expect(summarizeMemberNames(['A', 'B', 'C'])).toBe('A、B、C')
  })

  it('truncates long lists', () => {
    expect(summarizeMemberNames(['1', '2', '3', '4', '5', '6'])).toBe('1、2、3、4、5 等 6 个')
  })

  it('returns dash for empty', () => {
    expect(summarizeMemberNames([])).toBe('—')
  })
})
