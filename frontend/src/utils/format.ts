export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

/** 主力净比（数值已是百分比口径，展示不加 %） */
export function fmtNetRatio(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}`
}

export function fmtMoney(v: number | null | undefined): string {
  const n = Number(v || 0)
  const abs = Math.abs(n)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(1)}万`
  return `${sign}${abs.toFixed(0)}`
}

/** 表格窄列展示：万/亿单位不保留多余小数，避免换行 */
export function fmtMoneyCompact(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—'
  const n = Number(v)
  const abs = Math.abs(n)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${sign}${Math.round(abs / 1e4)}万`
  return `${sign}${Math.round(abs)}`
}

export function toYi(v: number | null | undefined): number {
  return Number(v || 0) / 1e8
}

export function chgTone(v: number | null | undefined): 'up' | 'down' | 'flat' {
  const n = Number(v || 0)
  if (n > 0) return 'up'
  if (n < 0) return 'down'
  return 'flat'
}

export function toneClass(tone: 'up' | 'down' | 'flat'): string {
  if (tone === 'up') return 'text-up'
  if (tone === 'down') return 'text-down'
  return 'text-flat'
}

const SECTOR_TYPE_LABELS: Record<string, string> = {
  industry: '行业',
  concept: '概念',
  industry2: '二级行业',
  classic_index: '板块指数',
  style: '风格',
  region: '地域',
}

export function fmtSectorType(type: string | null | undefined): string {
  if (!type) return '—'
  return SECTOR_TYPE_LABELS[type.toLowerCase()] ?? type
}

export function inferSectorTypeFromId(id: string): string | undefined {
  const code = id.trim()
  if (/^880\d{3}$/.test(code)) return 'classic_index'
  return undefined
}

export function resolveSectorType(item: {
  sector_type?: string | null
  id: string
}): string | undefined {
  return item.sector_type ?? inferSectorTypeFromId(item.id) ?? undefined
}

export function sectorTypeShort(type: string | null | undefined, id?: string): string {
  const resolved = type ?? (id ? inferSectorTypeFromId(id) : undefined)
  if (!resolved) return '板块'
  const shorts: Record<string, string> = {
    industry: '行业',
    concept: '概念',
    industry2: '二级',
    classic_index: '指数',
    style: '风格',
    region: '地域',
  }
  return shorts[resolved.toLowerCase()] ?? fmtSectorType(resolved)
}

export function fmtSectorSeriesLabel(item: {
  name: string
  id: string
  sector_type?: string | null
}): string {
  return `${item.name}·${sectorTypeShort(item.sector_type, item.id)}`
}

const BOARD_TYPE_LABELS: Record<string, string> = {
  HY: '行业',
  GN: '概念',
  HY2: '二级行业',
  IDX: '板块指数',
  FG: '风格',
  DQ: '地域',
  ALL: '全部',
}

export function boardTypeLabel(board: {
  board_type?: string
  sector_mode?: string
  selected_boards?: unknown[]
}): string {
  const selectedCount = (board.selected_boards || []).length
  if (board.sector_mode === 'selected' || selectedCount > 0) {
    return `自选 ${selectedCount} 个`
  }
  const type = board.board_type || 'HY'
  return `自动 · ${BOARD_TYPE_LABELS[type] || type}`
}
