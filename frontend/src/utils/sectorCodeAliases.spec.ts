import { describe, expect, it } from 'vitest'
import {
  isClassicIndexCodeQuery,
  isLegacyBlockCode,
  legacySectorSearchHint,
} from './sectorCodeAliases'

describe('sectorCodeAliases', () => {
  it('detects full classic index codes', () => {
    expect(isLegacyBlockCode('880490')).toBe(true)
    expect(isLegacyBlockCode('881338')).toBe(false)
  })

  it('detects classic index prefix queries', () => {
    expect(isClassicIndexCodeQuery('880')).toBe(true)
    expect(isClassicIndexCodeQuery('88049')).toBe(true)
    expect(isClassicIndexCodeQuery('880490')).toBe(true)
    expect(isClassicIndexCodeQuery('881338')).toBe(false)
  })

  it('hints to switch tab when searching 880 on industry tab', () => {
    expect(legacySectorSearchHint('880', 'HY')).toMatch(/板块指数/)
    expect(legacySectorSearchHint('880490', 'IDX')).toMatch(/未找到/)
    expect(legacySectorSearchHint('880', 'IDX')).toBeNull()
  })
})
