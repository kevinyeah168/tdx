import { apiGet } from '@/api/client'
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
}

export interface SectorFundFlowPayload {
  sector_id: string
  latest_complete_minute: string
  fund_tiers: string[]
  points: CurvePoint[]
  change_pct?: number | null
}

export interface SectorMemberRankItem {
  symbol: string
  name: string
  main_cumulative: number
  change_pct: number
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

export function fetchSectors(): Promise<SectorListResponse> {
  return apiGet<SectorListResponse>('/api/v1/sectors')
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
