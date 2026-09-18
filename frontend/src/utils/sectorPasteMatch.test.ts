import { describe, expect, it } from 'vitest'

import {
  collectCheckedSectorIds,
  matchPastedSectors,
  parsePastedSectorTokens,
  summarizePasteMatches,
} from '@/utils/sectorPasteMatch'

const catalog = [
  { sector_id: '880550', name: 'PCB概念', sector_type: 'concept' },
  { sector_id: '881001', name: '银行', sector_type: 'industry' },
  { sector_id: '881002', name: '人工智能', sector_type: 'concept' },
  { sector_id: '881003', name: '银行概念', sector_type: 'concept' },
]

describe('parsePastedSectorTokens', () => {
  it('splits by newline and comma', () => {
    expect(parsePastedSectorTokens('PCB概念\n银行,人工智能')).toEqual([
      'PCB概念',
      '银行',
      '人工智能',
    ])
  })

  it('strips list prefixes and dedupes', () => {
    expect(parsePastedSectorTokens('1. PCB概念\n2、银行\nPCB概念')).toEqual(['PCB概念', '银行'])
  })

  it('extracts tdx formula lines', () => {
    expect(parsePastedSectorTokens("C07:='880494';{互联网}")).toEqual(['880494', '互联网'])
  })
})

describe('matchPastedSectors', () => {
  it('matches code and exact name', () => {
    const rows = matchPastedSectors('880550\n银行', catalog)
    expect(rows[0]?.status).toBe('matched')
    expect(rows[0]?.selectedId).toBe('880550')
    expect(rows[1]?.status).toBe('matched')
    expect(rows[1]?.selectedId).toBe('881001')
  })

  it('flags ambiguous partial names', () => {
    const rows = matchPastedSectors('概念', catalog)
    expect(rows[0]?.status).toBe('ambiguous')
    expect(rows[0]?.candidates.length).toBeGreaterThan(1)
  })

  it('marks existing members', () => {
    const rows = matchPastedSectors('PCB概念', catalog, new Set(['880550']))
    expect(rows[0]?.status).toBe('existing')
    expect(rows[0]?.checked).toBe(false)
  })

  it('summarizes selected rows', () => {
    const rows = matchPastedSectors('880550\n未知板块', catalog)
    const summary = summarizePasteMatches(rows)
    expect(summary.matched).toBe(1)
    expect(summary.unmatched).toBe(1)
    expect(summary.selected).toBe(1)
    expect(collectCheckedSectorIds(rows)).toEqual(['880550'])
  })
})
