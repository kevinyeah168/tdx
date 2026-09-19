import { resolveSectorType } from '@/utils/format'

export type SectorTypeTone =
  | 'industry'
  | 'concept'
  | 'industry2'
  | 'classic_index'
  | 'style'
  | 'region'
  | 'custom'
  | 'default'

export function sectorTypeTone(
  type: string | null | undefined,
  id?: string,
): SectorTypeTone {
  const resolved = resolveSectorType({ sector_type: type, id: id ?? '' })?.toLowerCase()
  switch (resolved) {
    case 'industry':
      return 'industry'
    case 'concept':
      return 'concept'
    case 'industry2':
      return 'industry2'
    case 'classic_index':
      return 'classic_index'
    case 'style':
      return 'style'
    case 'region':
      return 'region'
    case 'custom':
      return 'custom'
    default:
      return 'default'
  }
}

export function sectorTypeClass(type: string | null | undefined, id?: string): string {
  return `sector-tone-${sectorTypeTone(type, id)}`
}

export const SECTOR_TYPE_LEGEND: { tone: SectorTypeTone; label: string }[] = [
  { tone: 'industry', label: '行业' },
  { tone: 'concept', label: '概念' },
  { tone: 'industry2', label: '二级' },
  { tone: 'classic_index', label: '指数' },
]

export const BOARD_TAB_TONE: Record<string, SectorTypeTone> = {
  ALL: 'default',
  HY: 'industry',
  GN: 'concept',
  HY2: 'industry2',
  IDX: 'classic_index',
  CUSTOM: 'custom',
}
