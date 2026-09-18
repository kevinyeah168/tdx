export type PasteMatchStatus = 'matched' | 'ambiguous' | 'unmatched' | 'existing' | 'duplicate'

export interface SectorCatalogItem {
  sector_id: string
  name: string
  sector_type?: string
}

export interface PasteMatchRow {
  token: string
  status: PasteMatchStatus
  candidates: SectorCatalogItem[]
  selectedId: string | null
  checked: boolean
}

export interface PasteMatchSummary {
  total: number
  matched: number
  ambiguous: number
  unmatched: number
  existing: number
  duplicate: number
  selected: number
}

function extractTokensFromPart(part: string): string[] {
  const trimmed = part.trim()
  if (!trimmed) return []

  const extracted: string[] = []
  for (const code of trimmed.match(/\d{6}/g) ?? []) {
    extracted.push(code)
  }
  for (const name of trimmed.match(/\{([^}]+)\}/g) ?? []) {
    extracted.push(name.slice(1, -1).trim())
  }
  for (const name of trimmed.match(/[（(]([^）)]+)[）)]/g) ?? []) {
    const inner = name.replace(/^[（(]|[）)]$/g, '').trim()
    if (inner) extracted.push(inner)
  }

  if (extracted.length) return extracted

  let token = trimmed.replace(/^["'「【\[]+|["'」】\]]+$/g, '')
  token = token.replace(/^[A-Za-z]+\d*:?=/, '').replace(/['";]/g, ' ').trim()
  token = token.replace(/^\d+[.、)\]]\s*/, '').trim()
  return token ? [token] : []
}

export function parsePastedSectorTokens(text: string): string[] {
  const normalized = text.replace(/\r\n/g, '\n')
  const parts = normalized.split(/[\n,，;；\t|]+/)
  const tokens: string[] = []
  const seen = new Set<string>()
  for (const part of parts) {
    for (const token of extractTokensFromPart(part)) {
      const key = token.toLowerCase()
      if (!token || seen.has(key)) continue
      seen.add(key)
      tokens.push(token)
    }
  }
  return tokens
}

function matchByCode(
  token: string,
  catalog: SectorCatalogItem[],
  byId: Map<string, SectorCatalogItem>,
): SectorCatalogItem[] {
  const normalized = token.trim()
  if (!/^\d{6}$/.test(normalized)) return []
  const hit = byId.get(normalized)
  if (hit) return [hit]
  return catalog.filter((item) => item.sector_id === normalized)
}

function matchByName(token: string, catalog: SectorCatalogItem[]): SectorCatalogItem[] {
  const lower = token.trim().toLowerCase()
  if (!lower) return []
  const exact = catalog.filter((item) => item.name.trim().toLowerCase() === lower)
  if (exact.length) return exact
  const partial = catalog.filter(
    (item) =>
      item.name.toLowerCase().includes(lower) ||
      item.sector_id.includes(token.trim()) ||
      lower.includes(item.name.toLowerCase()),
  )
  return partial
}

function resolveRowStatus(
  token: string,
  candidates: SectorCatalogItem[],
  existingIds: Set<string>,
  batchIds: Set<string>,
): PasteMatchRow {
  if (!candidates.length) {
    return {
      token,
      status: 'unmatched',
      candidates: [],
      selectedId: null,
      checked: false,
    }
  }
  if (candidates.length > 1) {
    return {
      token,
      status: 'ambiguous',
      candidates,
      selectedId: null,
      checked: false,
    }
  }
  const sector = candidates[0]!
  if (existingIds.has(sector.sector_id)) {
    return {
      token,
      status: 'existing',
      candidates,
      selectedId: sector.sector_id,
      checked: false,
    }
  }
  if (batchIds.has(sector.sector_id)) {
    return {
      token,
      status: 'duplicate',
      candidates,
      selectedId: sector.sector_id,
      checked: false,
    }
  }
  batchIds.add(sector.sector_id)
  return {
    token,
    status: 'matched',
    candidates,
    selectedId: sector.sector_id,
    checked: true,
  }
}

export function matchPastedSectors(
  text: string,
  catalog: SectorCatalogItem[],
  existingIds: Iterable<string> = [],
): PasteMatchRow[] {
  const tokens = parsePastedSectorTokens(text)
  const byId = new Map(catalog.map((item) => [item.sector_id, item]))
  const existing = new Set(existingIds)
  const batchIds = new Set<string>()
  const rows: PasteMatchRow[] = []

  for (const token of tokens) {
    const codeHits = matchByCode(token, catalog, byId)
    if (codeHits.length) {
      rows.push(resolveRowStatus(token, codeHits, existing, batchIds))
      continue
    }
    const nameHits = matchByName(token, catalog)
    rows.push(resolveRowStatus(token, nameHits, existing, batchIds))
  }
  return rows
}

export function summarizePasteMatches(rows: PasteMatchRow[]): PasteMatchSummary {
  const summary: PasteMatchSummary = {
    total: rows.length,
    matched: 0,
    ambiguous: 0,
    unmatched: 0,
    existing: 0,
    duplicate: 0,
    selected: 0,
  }
  for (const row of rows) {
    if (row.status === 'matched') summary.matched += 1
    if (row.status === 'ambiguous') summary.ambiguous += 1
    if (row.status === 'unmatched') summary.unmatched += 1
    if (row.status === 'existing') summary.existing += 1
    if (row.status === 'duplicate') summary.duplicate += 1
    if (row.checked && row.selectedId) summary.selected += 1
  }
  return summary
}

export function applyAmbiguousSelection(
  rows: PasteMatchRow[],
  rowIndex: number,
  sectorId: string,
  existingIds: Set<string>,
): PasteMatchRow[] {
  const next = rows.map((row) => ({ ...row, candidates: [...row.candidates] }))
  const target = next[rowIndex]
  if (!target || target.status !== 'ambiguous') return next

  const sector = target.candidates.find((item) => item.sector_id === sectorId)
  if (!sector) return next

  const batchIds = new Set<string>()
  for (const row of next) {
    if (row.checked && row.selectedId) batchIds.add(row.selectedId)
  }

  if (existingIds.has(sector.sector_id)) {
    target.status = 'existing'
    target.selectedId = sector.sector_id
    target.checked = false
    return next
  }
  if (batchIds.has(sector.sector_id)) {
    target.status = 'duplicate'
    target.selectedId = sector.sector_id
    target.checked = false
    return next
  }

  target.status = 'matched'
  target.selectedId = sector.sector_id
  target.checked = true
  return next
}

export function togglePasteRowChecked(
  rows: PasteMatchRow[],
  rowIndex: number,
  checked: boolean,
): PasteMatchRow[] {
  const next = rows.map((row) => ({ ...row, candidates: [...row.candidates] }))
  const target = next[rowIndex]
  if (!target || !target.selectedId) return next
  if (target.status === 'existing' || target.status === 'unmatched') return next
  if (checked) {
    const usedElsewhere = next.some(
      (row, index) => index !== rowIndex && row.checked && row.selectedId === target.selectedId,
    )
    if (usedElsewhere) return next
    target.checked = true
    if (target.status === 'ambiguous' || target.status === 'duplicate') {
      target.status = 'matched'
    }
  } else {
    target.checked = false
  }
  return next
}

export function collectCheckedSectorIds(rows: PasteMatchRow[]): string[] {
  const ids: string[] = []
  const seen = new Set<string>()
  for (const row of rows) {
    if (!row.checked || !row.selectedId || seen.has(row.selectedId)) continue
    seen.add(row.selectedId)
    ids.push(row.selectedId)
  }
  return ids
}
