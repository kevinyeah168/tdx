import { apiGet } from '@/api/client'

export interface TdxProbeSummary {
  vipdoc_ok: boolean
  tnf_ok: boolean
  mac_reachable: boolean
  client_likely_running: boolean
  ok: boolean
}

export interface SettingsDetail {
  retention_days: number
  tdx_home: string
  collect_mode: 'selective' | 'full'
  archive_full_enabled: boolean
  priority_max_sectors: number
  priority_max_stocks: number
  priority_sector_members: number
  priority_linkage_members: number
  tdx_probe?: TdxProbeSummary | null
}

export interface SettingsUpdatePayload {
  retention_days?: number
  tdx_home?: string
  collect_mode?: 'selective' | 'full'
  archive_full_enabled?: boolean
}

export interface CollectionTargets {
  sector_ids: string[]
  symbols?: string[]
  manual_symbols?: string[]
  resolved_symbol_count?: number
  priority_max_sectors: number
  priority_max_stocks: number
  priority_sector_members: number
  priority_linkage_members: number
}

export interface UiSelectedBoard {
  id: string
  name: string
}

export interface TdxProbeResult {
  tdx_home: string
  vipdoc_ok: boolean
  tnf_ok: boolean
  mac_reachable: boolean
  client_likely_running: boolean
  ok: boolean
  mac_port: number
  sample_day_file?: string | null
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

export async function fetchSettingsDetail(includeProbe = false): Promise<SettingsDetail> {
  return apiGet<SettingsDetail>('/api/v1/settings', { probe: includeProbe ? 'true' : 'false' })
}

export async function updateSettingsDetail(payload: SettingsUpdatePayload): Promise<SettingsDetail> {
  return apiJson<SettingsDetail>('/api/v1/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function fetchCollectionTargets(includeResolved = false): Promise<CollectionTargets> {
  return apiGet<CollectionTargets>('/api/v1/settings/collection-targets', {
    include_symbols: includeResolved ? 'true' : 'false',
  })
}

export async function fetchUiSelectedBoards(): Promise<{ boards: UiSelectedBoard[]; source: string }> {
  return apiGet('/api/v1/settings/ui-selected-boards')
}

export async function saveCollectionTargets(payload: {
  sector_ids: string[]
  symbols: string[]
}): Promise<{ ok: boolean; sector_count: number; symbol_count: number; manual_symbol_count?: number }> {
  return apiJson('/api/v1/settings/collection-targets', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function probeTdxHome(tdxHome: string): Promise<TdxProbeResult> {
  return apiJson<TdxProbeResult>('/api/v1/settings/tdx-probe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tdx_home: tdxHome }),
  })
}

export async function restartCollectors(): Promise<{ ok: boolean }> {
  return apiJson('/api/v1/settings/restart-collectors', { method: 'POST' })
}

export async function fetchSettingsAuditLog(limit = 20): Promise<{ items: Array<Record<string, unknown>> }> {
  return apiGet('/api/v1/settings/audit-log', { limit: String(limit) })
}

// Legacy helpers used elsewhere
export interface SettingsResponse {
  retention_days: number
}

export async function fetchSettings(): Promise<SettingsResponse> {
  const detail = await fetchSettingsDetail()
  return { retention_days: detail.retention_days }
}

export async function updateSettings(retentionDays: number): Promise<SettingsResponse> {
  const detail = await updateSettingsDetail({ retention_days: retentionDays })
  return { retention_days: detail.retention_days }
}
