import { apiGet } from '@/api/client'

export const MAX_GROUP_MEMBERS = 50

export interface StockGroupMember {
  symbol: string
  name: string
}

export interface StockGroup {
  id: string
  name: string
  sort_order: number
  symbol_ids: string[]
  symbols: StockGroupMember[]
}

export interface StockGroupsResponse {
  items: StockGroup[]
  active_group_id: string
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

export async function fetchStockGroups(): Promise<StockGroupsResponse> {
  return apiGet<StockGroupsResponse>('/api/v1/settings/stock-groups')
}

export async function createStockGroup(name: string): Promise<StockGroup> {
  const result = await apiJson<{ ok: boolean; group: StockGroup }>('/api/v1/settings/stock-groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return result.group
}

export async function renameStockGroup(groupId: string, name: string): Promise<StockGroup> {
  const result = await apiJson<{ ok: boolean; group: StockGroup }>(
    `/api/v1/settings/stock-groups/${groupId}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    },
  )
  return result.group
}

export async function deleteStockGroup(groupId: string): Promise<void> {
  await apiJson(`/api/v1/settings/stock-groups/${groupId}`, { method: 'DELETE' })
}

export async function setActiveStockGroup(groupId: string): Promise<string> {
  const result = await apiJson<{ ok: boolean; active_group_id: string }>(
    '/api/v1/settings/stock-groups/active',
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: groupId }),
    },
  )
  return result.active_group_id
}

export async function addStockGroupMembers(groupId: string, symbols: string[]): Promise<StockGroup> {
  const result = await apiJson<{ ok: boolean; group: StockGroup }>(
    `/api/v1/settings/stock-groups/${groupId}/members`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols }),
    },
  )
  return result.group
}

export async function removeStockGroupMember(groupId: string, symbol: string): Promise<StockGroup> {
  const result = await apiJson<{ ok: boolean; group: StockGroup }>(
    `/api/v1/settings/stock-groups/${groupId}/members/${symbol}`,
    { method: 'DELETE' },
  )
  return result.group
}
