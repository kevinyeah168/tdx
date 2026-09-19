export function summarizeMemberNames(names: string[], maxVisible = 5): string {
  const cleaned = names.map((name) => name.trim()).filter(Boolean)
  if (!cleaned.length) return '—'
  if (cleaned.length <= maxVisible) return cleaned.join('、')
  return `${cleaned.slice(0, maxVisible).join('、')} 等 ${cleaned.length} 个`
}
