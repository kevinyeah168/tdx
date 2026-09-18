import { apiGet } from '@/api/client'

export const MAX_GROUP_MEMBERS = 30
export const MAX_GROUP_CHART_VISIBLE = 30

export interface SectorGroupMember {
  sector_id: string
  name: string
  chart_visible: boolean
}

export interface SectorGroup {
  id: string
  name: string
  sort_order: number
  sector_ids: string[]
  sectors: SectorGroupMember[]
}

export interface SectorGroupsResponse {
  items: SectorGroup[]
  active_group_id: string
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

export async function fetchSectorGroups(): Promise<SectorGroupsResponse> {
  return apiGet<SectorGroupsResponse>('/api/v1/settings/sector-groups')
}

export async function createSectorGroup(name: string): Promise<SectorGroup> {
  const result = await apiJson<{ ok: boolean; group: SectorGroup }>('/api/v1/settings/sector-groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return result.group
}

export async function renameSectorGroup(groupId: string, name: string): Promise<SectorGroup> {
  const result = await apiJson<{ ok: boolean; group: SectorGroup }>(
    `/api/v1/settings/sector-groups/${groupId}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    },
  )
  return result.group
}

export async function deleteSectorGroup(groupId: string): Promise<void> {
  await apiJson(`/api/v1/settings/sector-groups/${groupId}`, { method: 'DELETE' })
}

export async function setActiveSectorGroup(groupId: string): Promise<string> {
  const result = await apiJson<{ ok: boolean; active_group_id: string }>(
    '/api/v1/settings/sector-groups/active',
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: groupId }),
    },
  )
  return result.active_group_id
}

export async function addSectorGroupMembers(groupId: string, sectorIds: string[]): Promise<SectorGroup> {
  const result = await apiJson<{ ok: boolean; group: SectorGroup }>(
    `/api/v1/settings/sector-groups/${groupId}/members`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sector_ids: sectorIds }),
    },
  )
  return result.group
}

export async function removeSectorGroupMember(groupId: string, sectorId: string): Promise<SectorGroup> {
  const result = await apiJson<{ ok: boolean; group: SectorGroup }>(
    `/api/v1/settings/sector-groups/${groupId}/members/${sectorId}`,
    { method: 'DELETE' },
  )
  return result.group
}

export async function setSectorGroupMemberChartVisible(
  groupId: string,
  sectorId: string,
  chartVisible: boolean,
): Promise<SectorGroup> {
  const result = await apiJson<{ ok: boolean; group: SectorGroup }>(
    `/api/v1/settings/sector-groups/${groupId}/members/${sectorId}/chart-visible`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chart_visible: chartVisible }),
    },
  )
  return result.group
}
