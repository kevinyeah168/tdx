import { apiGet, apiPost, isApiNotFound } from '@/api/client'
import type { SectorListResponse } from '@/types/api'

export interface CurveValue {
  delta: number
  cumulative: number
  source: string
  quality: string
}

export interface CurvePoint {
  minute: string
  values: Record<string, CurveValue>
  close?: number | null
  change_pct?: number | null
  amount_delta?: number | null
}

export interface SectorFundFlowPayload {
  sector_id: string
  latest_complete_minute: string
  fund_tiers: string[]
  points: CurvePoint[]
  change_pct?: number | null
  pre_close?: number | null
}

export interface SectorMemberRankItem {
  symbol: string
  name: string
  main_cumulative: number
  gray_cumulative?: number | null
  change_pct: number
  free_float_market_cap?: number | null
  main_net_ratio?: number | null
  free_float_market_cap_avg?: number | null
  main_net_ratio_avg?: number | null
}

export interface SectorMemberRankResponse {
  sector_id: string
  trade_date: string
  minute: string
  items: SectorMemberRankItem[]
}

export interface SectorRankItem {
  sector_id: string
  name: string
  sector_type: string
  main_cumulative: number
  change_pct: number
}

export interface SectorRankResponse {
  trade_date: string
  minute: string
  items: SectorRankItem[]
}

export interface SectorSnapshotItem {
  sector_id: string
  main_cumulative: number
  change_pct: number
}

export interface SectorSnapshotResponse {
  trade_date: string
  minute: string
  items: SectorSnapshotItem[]
}

export interface SectorBreadthCounts {
  limit_up: number
  limit_down: number
  up: number
  down: number
  flat: number
  sampled: number
  total_members: number
}

export interface SectorBreadthResponse {
  sector_id: string
  trade_date: string
  minute: string
  counts: SectorBreadthCounts
  limit_up: SectorMemberRankItem[]
  limit_down: SectorMemberRankItem[]
  up: SectorMemberRankItem[]
  down: SectorMemberRankItem[]
}

export interface SectorCatalogMembersResponse {
  sector_id: string
  items: Array<{ symbol: string; name: string }>
}

export function fetchSectorCatalogMembers(
  sectorId: string,
  sectorName?: string,
): Promise<SectorCatalogMembersResponse> {
  const params: Record<string, string> = {}
  if (sectorName?.trim()) params.name = sectorName.trim()
  return apiGet<SectorCatalogMembersResponse>(`/api/v1/sectors/${sectorId}/catalog-members`, params)
}

export function fetchSectors(params?: { q?: string; limit?: number }): Promise<SectorListResponse> {
  const query: Record<string, string> = {}
  if (params?.q?.trim()) query.q = params.q.trim()
  if (params?.limit != null) query.limit = String(params.limit)
  return apiGet<SectorListResponse>('/api/v1/sectors', Object.keys(query).length ? query : undefined)
}

export function searchSectors(query: string, limit = 30): Promise<SectorListResponse> {
  return fetchSectors({ q: query, limit })
}

export function fetchSectorRank(
  tradeDate: string,
  minute?: string | null,
  limit = 12,
): Promise<SectorRankResponse> {
  const params: Record<string, string> = {
    date: tradeDate,
    limit: String(limit),
  }
  if (minute) params.minute = minute
  return apiGet<SectorRankResponse>('/api/v1/sectors/rank', params)
}

export function fetchSectorSnapshot(
  sectorIds: string[],
  tradeDate: string,
  minute: string,
): Promise<SectorSnapshotResponse> {
  if (!sectorIds.length) {
    return Promise.resolve({ trade_date: tradeDate, minute, items: [] })
  }
  return apiGet<SectorSnapshotResponse>('/api/v1/sectors/snapshot', {
    date: tradeDate,
    minute,
    ids: sectorIds.join(','),
  })
}

export function fetchSectorMembers(
  sectorId: string,
  tradeDate: string,
  minute: string,
  limit = 100,
  sectorName?: string,
): Promise<SectorMemberRankResponse> {
  const params: Record<string, string> = {
    date: tradeDate,
    minute,
    limit: String(limit),
  }
  if (sectorName?.trim()) params.name = sectorName.trim()
  return apiGet<SectorMemberRankResponse>(`/api/v1/sectors/${sectorId}/members`, params)
}

export function fetchSectorFundFlow(sectorId: string, tradeDate: string): Promise<SectorFundFlowPayload> {
  return apiGet<SectorFundFlowPayload>(`/api/v1/sectors/${sectorId}/minutes`, { date: tradeDate })
}

export interface SectorFundFlowBatchResponse {
  trade_date: string
  items: SectorFundFlowPayload[]
}

export async function fetchSectorFundFlowBatch(
  sectorIds: string[],
  tradeDate: string,
): Promise<SectorFundFlowBatchResponse> {
  if (!sectorIds.length) {
    return { trade_date: tradeDate, items: [] }
  }
  try {
    return await apiPost<SectorFundFlowBatchResponse>(
      '/api/v1/sectors/fund-flow/batch',
      { ids: sectorIds },
      { date: tradeDate },
    )
  } catch (error) {
    if (!isApiNotFound(error)) throw error
    const items = (
      await Promise.all(
        sectorIds.map(async (sectorId) => {
          try {
            return await fetchSectorFundFlow(sectorId, tradeDate)
          } catch {
            return null
          }
        }),
      )
    ).filter((item): item is SectorFundFlowPayload => item != null)
    return { trade_date: tradeDate, items }
  }
}

export function fetchSectorBreadth(
  sectorId: string,
  tradeDate: string,
  minute: string,
): Promise<SectorBreadthResponse> {
  return apiGet<SectorBreadthResponse>(`/api/v1/sectors/${sectorId}/breadth`, {
    date: tradeDate,
    minute,
  })
}

export interface SectorGrayFlowPoint {
  minute: string
  dark_cumulative: number
  open_cumulative?: number | null
  total_cumulative?: number | null
  source?: string | null
}

export interface SectorGrayFlowPayload {
  sector_id: string
  latest_complete_minute: string
  member_count?: number | null
  gray_covered_count?: number | null
  coverage_pct?: number | null
  source?: string | null
  quality?: string | null
  points: SectorGrayFlowPoint[]
}

export function fetchSectorGrayFlow(
  sectorId: string,
  tradeDate: string,
): Promise<SectorGrayFlowPayload> {
  return apiGet<SectorGrayFlowPayload>(`/api/v1/sectors/${sectorId}/gray-flow`, {
    date: tradeDate,
  })
}

export interface SectorGrayFlowBatchResponse {
  trade_date: string
  items: SectorGrayFlowPayload[]
}

export async function fetchSectorGrayFlowBatch(
  sectorIds: string[],
  tradeDate: string,
): Promise<SectorGrayFlowBatchResponse> {
  if (!sectorIds.length) {
    return { trade_date: tradeDate, items: [] }
  }
  try {
    return await apiPost<SectorGrayFlowBatchResponse>(
      '/api/v1/sectors/gray-flow/batch',
      { ids: sectorIds },
      { date: tradeDate },
    )
  } catch (error) {
    if (!isApiNotFound(error)) throw error
    const items = (
      await Promise.all(
        sectorIds.map(async (sectorId) => {
          try {
            return await fetchSectorGrayFlow(sectorId, tradeDate)
          } catch {
            return null
          }
        }),
      )
    ).filter((item): item is SectorGrayFlowPayload => item != null)
    return { trade_date: tradeDate, items }
  }
}
