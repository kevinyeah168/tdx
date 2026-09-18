export function parseStockPasteText(text: string): string[] {
  const seen = new Set<string>()
  const tokens: string[] = []
  for (const raw of text.split(/[\s,;，；\n\r\t]+/)) {
    const token = raw.trim()
    if (!token || seen.has(token)) continue
    seen.add(token)
    tokens.push(token)
  }
  return tokens
}
