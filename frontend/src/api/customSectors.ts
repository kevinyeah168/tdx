import { apiGet } from '@/api/client'

export const MAX_CUSTOM_SECTOR_MEMBERS = 60

export interface CustomSectorMember {
  symbol: string
  name: string
}

export type CustomSectorSourceType = 'manual' | 'directory'

export interface CustomSector {
  sector_id: string
  name: string
  sort_order: number
  source_type: CustomSectorSourceType
  symbols: string[]
  members: CustomSectorMember[]
}

export interface CustomSectorsResponse {
  items: CustomSector[]
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

export async function fetchCustomSectors(): Promise<CustomSectorsResponse> {
  return apiGet<CustomSectorsResponse>('/api/v1/settings/custom-sectors')
}

export async function createCustomSector(name: string): Promise<CustomSector> {
  const result = await apiJson<{ ok: boolean; sector: CustomSector }>(
    '/api/v1/settings/custom-sectors',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    },
  )
  return result.sector
}

export async function renameCustomSector(sectorId: string, name: string): Promise<CustomSector> {
  const result = await apiJson<{ ok: boolean; sector: CustomSector }>(
    `/api/v1/settings/custom-sectors/${sectorId}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    },
  )
  return result.sector
}

export async function deleteCustomSector(sectorId: string): Promise<void> {
  await apiJson(`/api/v1/settings/custom-sectors/${sectorId}`, { method: 'DELETE' })
}

export async function addCustomSectorMembers(
  sectorId: string,
  symbols: string[],
): Promise<CustomSector> {
  const result = await apiJson<{ ok: boolean; sector: CustomSector }>(
    `/api/v1/settings/custom-sectors/${sectorId}/members`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols }),
    },
  )
  return result.sector
}

export async function removeCustomSectorMember(
  sectorId: string,
  symbol: string,
): Promise<CustomSector> {
  const result = await apiJson<{ ok: boolean; sector: CustomSector }>(
    `/api/v1/settings/custom-sectors/${sectorId}/members/${symbol}`,
    { method: 'DELETE' },
  )
  return result.sector
}

export interface CustomSectorSyncFileSummary {
  file_name: string
  sector_name: string
  sector_id: string
  member_count: number
  unresolved_count: number
  skipped?: boolean
  skip_reason?: string | null
}

export interface CustomSectorSyncSummary {
  directory: string
  files_seen: number
  sectors_updated: number
  sectors_deleted?: number
  members_total: number
  unresolved_total: number
  errors: string[]
  files: CustomSectorSyncFileSummary[]
  deleted_sectors?: Array<{ sector_name: string; sector_id: string }>
}

export interface CustomSectorSyncConfig {
  directory_path: string
  auto_sync_enabled: boolean
  interval_seconds: number
  last_sync_at: string | null
  last_sync_error: string | null
  last_sync_summary: CustomSectorSyncSummary | null
}

export async function fetchCustomSectorSyncConfig(): Promise<CustomSectorSyncConfig> {
  const result = await apiGet<{ ok: boolean; config: CustomSectorSyncConfig }>(
    '/api/v1/settings/custom-sectors/sync-directory',
  )
  return result.config
}

export async function saveCustomSectorSyncConfig(
  config: Pick<CustomSectorSyncConfig, 'directory_path' | 'auto_sync_enabled' | 'interval_seconds'>,
): Promise<CustomSectorSyncConfig> {
  const result = await apiJson<{ ok: boolean; config: CustomSectorSyncConfig }>(
    '/api/v1/settings/custom-sectors/sync-directory',
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    },
  )
  return result.config
}

export async function pickCustomSectorDirectory(
  initialPath?: string,
): Promise<{ cancelled: boolean; directory_path: string }> {
  const result = await apiJson<{
    ok: boolean
    cancelled: boolean
    directory_path: string
  }>('/api/v1/settings/custom-sectors/pick-directory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ initial_path: initialPath ?? null }),
  })
  return { cancelled: result.cancelled, directory_path: result.directory_path }
}

export async function syncCustomSectorDirectory(
  directoryPath?: string,
): Promise<{ summary: CustomSectorSyncSummary; items: CustomSector[]; config: CustomSectorSyncConfig }> {
  const result = await apiJson<{
    ok: boolean
    summary: CustomSectorSyncSummary
    items: CustomSector[]
    config: CustomSectorSyncConfig
  }>('/api/v1/settings/custom-sectors/sync-directory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ directory_path: directoryPath ?? null }),
  })
  return { summary: result.summary, items: result.items, config: result.config }
}
