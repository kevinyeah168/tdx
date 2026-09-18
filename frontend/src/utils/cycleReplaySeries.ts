import type { CurvePoint, SectorFundFlowPayload } from '@/api/sectors'
import type { FlowSeries } from '@/types/board'
import { inferSectorTypeFromId } from '@/utils/format'
import { alignValuesToTradingMinutes } from '@/utils/tradingTimeline'

export function endOfDayMainCumulative(points: CurvePoint[]): number | null {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const value = points[index]?.values.main?.cumulative
    if (value != null && Number.isFinite(value)) return value
  }
  return null
}

export function buildRangeFlowSeries(
  id: string,
  name: string,
  dateTimeline: string[],
  valuesByDate: Map<string, number | null>,
  extra?: { sector_type?: string | null; symbol?: string },
): FlowSeries | null {
  const values = dateTimeline.map((date) => valuesByDate.get(date) ?? null)
  if (!values.some((value) => value != null)) return null

  let cumMain = 0
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index] != null) {
      cumMain = values[index]!
      break
    }
  }

  return {
    id,
    name,
    symbol: extra?.symbol,
    sector_type: extra?.sector_type ?? null,
    cum_main: cumMain,
    change_pct: null,
    values,
  }
}

export function sectorPayloadToFlowSeries(
  sectorId: string,
  name: string,
  payload: SectorFundFlowPayload,
): FlowSeries | null {
  const points = payload.points
  if (!points.length) return null

  const timeline = points.map((point) => point.minute)
  const values = points.map((point) => point.values.main?.cumulative ?? null)
  const aligned = alignValuesToTradingMinutes(timeline, values)

  let cumMain = 0
  for (let index = aligned.length - 1; index >= 0; index -= 1) {
    if (aligned[index] != null) {
      cumMain = aligned[index]!
      break
    }
  }

  const last = points[points.length - 1]!
  return {
    id: sectorId,
    name,
    sector_type: inferSectorTypeFromId(sectorId),
    cum_main: cumMain,
    change_pct: payload.change_pct ?? last.change_pct ?? null,
    values: aligned,
  }
}

