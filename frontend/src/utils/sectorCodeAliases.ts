/**
 * 通达信 APP「板块指数」880xxx 与 MAC 行业 881xxx 是不同体系。
 * 880490 等指数不在 get_board_list 目录里，但 MAC 可查询（get_board_summary / get_stock_quotes）。
 */

export function isLegacyBlockCode(code: string): boolean {
  return /^880\d{3}$/.test(code.trim())
}

/** 完整或前缀搜索，如 880 / 88049 / 880490 */
export function isClassicIndexCodeQuery(query: string): boolean {
  const normalized = String(query ?? '').trim()
  if (!normalized) return false
  // Require a real 880 prefix query (880 / 8804 / 880490), never match empty.
  return /^880\d{0,3}$/.test(normalized)
}

export function legacySectorSearchHint(
  query: string,
  currentType?: 'ALL' | 'HY' | 'GN' | 'HY2' | 'IDX',
): string | null {
  const normalized = query.trim()
  if (!isClassicIndexCodeQuery(normalized) && !isLegacyBlockCode(normalized)) {
    return null
  }
  if (currentType === 'IDX') {
    if (isLegacyBlockCode(normalized)) {
      return `未找到 ${normalized}：请确认采集器已同步板块目录，或检查代码是否正确`
    }
    return null
  }
  return `880 开头为「板块指数」代码，请切换到「板块指数」Tab（行业/概念列表不含 880 指数）`
}
