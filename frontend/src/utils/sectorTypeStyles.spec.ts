import { describe, expect, it } from 'vitest'
import { sectorTypeClass, sectorTypeTone } from './sectorTypeStyles'

describe('sectorTypeStyles', () => {
  it('maps sector types to tone classes', () => {
    expect(sectorTypeTone('industry', '881319')).toBe('industry')
    expect(sectorTypeTone('classic_index', '880490')).toBe('classic_index')
    expect(sectorTypeClass('concept', '881121')).toBe('sector-tone-concept')
  })

  it('infers classic index tone from 880 code', () => {
    expect(sectorTypeTone(null, '880305')).toBe('classic_index')
    expect(sectorTypeClass(undefined, '880305')).toBe('sector-tone-classic_index')
  })
})
