import { describe, expect, it } from 'vitest'
import { fmtSectorSeriesLabel, inferSectorTypeFromId, sectorTypeShort } from './format'

describe('sector display labels', () => {
  it('infers classic index from 880 codes', () => {
    expect(inferSectorTypeFromId('880490')).toBe('classic_index')
    expect(inferSectorTypeFromId('881319')).toBeUndefined()
  })

  it('infers custom sector type from custom_ prefix', () => {
    expect(inferSectorTypeFromId('custom_abc123')).toBe('custom')
    expect(sectorTypeShort('custom', 'custom_abc123')).toBe('自定义')
  })

  it('builds disambiguated series labels', () => {
    expect(
      fmtSectorSeriesLabel({ name: '半导体', id: '881319', sector_type: 'industry' }),
    ).toBe('半导体·行业')
    expect(
      fmtSectorSeriesLabel({ name: '半导体', id: '880491', sector_type: 'classic_index' }),
    ).toBe('半导体·指数')
  })

  it('falls back to index label for 880 codes without sector_type', () => {
    expect(sectorTypeShort(null, '880305')).toBe('指数')
  })
})
