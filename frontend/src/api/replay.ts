import { apiGet } from '@/api/client'

export interface ReplayDatesResponse {
  dates: string[]
}

export interface ReplayMinutesResponse {
  trade_date: string
  minutes: string[]
  latest_complete_minute: string
  latest_sector_minute?: string | null
  latest_stock_minute?: string | null
  latest_available_minute?: string | null
}

let cachedReplayDates: ReplayDatesResponse | null = null

export function clearReplayDatesCache(): void {
  cachedReplayDates = null
}

export async function fetchReplayDates(): Promise<ReplayDatesResponse> {
  if (cachedReplayDates) return cachedReplayDates
  cachedReplayDates = await apiGet<ReplayDatesResponse>('/api/v1/replay/dates')
  return cachedReplayDates
}

export function fetchReplayMinutes(tradeDate: string): Promise<ReplayMinutesResponse> {
  return apiGet<ReplayMinutesResponse>('/api/v1/replay/minutes', { date: tradeDate })
}

export interface CollectorRoleStatus {
  online: boolean
  last_seen: string
}

export interface HealthDetailResponse {
  catalog_stale: boolean
  catalog_version: string | null
  latest_complete_minute: string | null
  coverage_pct: number | null
  unresolved_gaps: number
  collector_online: boolean
  collector_last_seen?: string | null
  collector_roles?: Record<string, CollectorRoleStatus>
}

export function fetchHealthDetail(): Promise<HealthDetailResponse> {
  return apiGet<HealthDetailResponse>('/api/v1/health/detail')
}
