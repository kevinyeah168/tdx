import type { FlowSeries } from '@/types/board'

const WARM_PALETTE = [
  '#E03030', '#E86A20', '#E8A020', '#22c55e', '#3b82f6',
  '#a855f7', '#06b6d4', '#f43f5e', '#84cc16', '#f59e0b',
]

const COOL_PALETTE = ['#22c55e', '#14b8a6', '#0ea5e9', '#6366f1', '#64748b']

const STOCK_PALETTE = [
  '#fe3ee1', '#2563eb', '#059669', '#d97706', '#7c3aed',
  '#0891b2', '#dc2626', '#4f46e5', '#0d9488', '#ea580c',
]

export function seriesColor(series: FlowSeries[], item: FlowSeries, kind: 'sector' | 'stock' = 'sector'): string {
  const idx = Math.max(0, series.findIndex((x) => x.id === item.id))
  const tail = Number(item.cum_main || 0)
  if (kind === 'stock') {
    return STOCK_PALETTE[idx % STOCK_PALETTE.length]
  }
  if (tail >= 0) return WARM_PALETTE[idx % WARM_PALETTE.length]
  return COOL_PALETTE[idx % COOL_PALETTE.length]
}

export const sectorColor = (series: FlowSeries[], item: FlowSeries) => seriesColor(series, item, 'sector')
export const stockColor = (series: FlowSeries[], item: FlowSeries) => seriesColor(series, item, 'stock')

export const STOCK_LINE_COLOR = '#fe3ee1'
