export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

export function fmtMoney(v: number | null | undefined): string {
  const n = Number(v || 0)
  const abs = Math.abs(n)
  const sign = n > 0 ? '+' : n < 0 ? '-' : ''
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(1)}万`
  return `${sign}${abs.toFixed(0)}`
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
  return 'text-[var(--muted)]'
}

const BOARD_TYPE_LABELS: Record<string, string> = {
  HY: '行业',
  GN: '概念',
  HY2: '二级行业',
  FG: '风格',
  DQ: '地域',
  ALL: '全部',
}

export function boardTypeLabel(board: {
  board_type?: string
  sector_mode?: string
  selected_boards?: unknown[]
}): string {
  if (board.sector_mode === 'selected') {
    return `自选 ${(board.selected_boards || []).length} 个`
  }
  const type = board.board_type || 'HY'
  return `自动 · ${BOARD_TYPE_LABELS[type] || type}`
}
