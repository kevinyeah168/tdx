import type { CurvePoint } from '@/api/sectors'
import type { StockGrayFlowPoint } from '@/api/stocks'
import type { FlowSeries } from '@/types/board'
import { alignValuesToTradingMinutes, TRADING_MINUTES } from '@/utils/tradingTimeline'

function computeAvgPriceValues(
  closes: (number | null)[],
  amountDeltas: (number | null)[],
): (number | null)[] {
  let cumAmount = 0
  let cumVolume = 0
  return closes.map((close, index) => {
    const amountDelta = amountDeltas[index]
    if (close != null && close > 0 && amountDelta != null && amountDelta > 0) {
      cumAmount += amountDelta
      cumVolume += amountDelta / close
    }
    if (cumVolume <= 0) return null
    return cumAmount / cumVolume
  })
}

function trimArraysToMinute(values: (number | null)[], replayMinute: string): (number | null)[] {
  const cutoff = TRADING_MINUTES.indexOf(replayMinute)
  if (cutoff < 0) return values
  return values.map((value, index) => (index <= cutoff ? value : null))
}

export function buildStockFlowSeries(
  symbol: string,
  name: string,
  points: CurvePoint[],
  changePct: number | null,
  replayMinute: string,
): FlowSeries | null {
  const trimmed = points.filter((point) => point.minute <= replayMinute)
  if (!trimmed.length) return null

  const timeline = trimmed.map((point) => point.minute)
  const values = trimmed.map((point) => point.values.main?.cumulative ?? null)
  const priceRaw = trimmed.map((point) =>
    point.close != null && Number.isFinite(point.close) ? point.close : null,
  )
  const amountDeltas = trimmed.map((point) =>
    point.amount_delta != null && Number.isFinite(point.amount_delta) ? point.amount_delta : null,
  )
  const avgRaw = computeAvgPriceValues(priceRaw, amountDeltas)

  const alignedValues = alignValuesToTradingMinutes(timeline, values)
  const alignedPrices = alignValuesToTradingMinutes(timeline, priceRaw)
  const alignedAvg = alignValuesToTradingMinutes(timeline, avgRaw)

  let cumMain = 0
  for (let index = alignedValues.length - 1; index >= 0; index -= 1) {
    if (alignedValues[index] != null) {
      cumMain = alignedValues[index]!
      break
    }
  }

  const lastPoint = trimmed[trimmed.length - 1]!
  const hasPrice = alignedPrices.some((value) => value != null)
  const hasAvg = alignedAvg.some((value) => value != null)

  return {
    id: symbol.toUpperCase(),
    name,
    symbol: symbol.toUpperCase(),
    cum_main: cumMain,
    change_pct: lastPoint.change_pct ?? changePct,
    values: alignedValues,
    price_values: hasPrice ? alignedPrices : undefined,
    avg_price_values: hasAvg ? alignedAvg : undefined,
  }
}

export function attachGrayToSeries(
  series: FlowSeries,
  grayPoints: StockGrayFlowPoint[],
  replayMinute: string,
): FlowSeries {
  const trimmed = grayPoints.filter((point) => point.minute <= replayMinute)
  if (!trimmed.length) return series

  const timeline = trimmed.map((point) => point.minute)
  const values = trimmed.map((point) => point.dark_cumulative ?? null)
  const gray_values = alignValuesToTradingMinutes(timeline, values)
  const lastPoint = trimmed[trimmed.length - 1]

  return {
    ...series,
    gray_values,
    cum_gray: lastPoint?.dark_cumulative ?? null,
  }
}

export function trimSeriesValuesToMinute(series: FlowSeries, replayMinute: string): FlowSeries {
  const values = trimArraysToMinute(series.values, replayMinute)
  let cumMain = 0
  const cutoff = TRADING_MINUTES.indexOf(replayMinute)
  for (let index = cutoff; index >= 0; index -= 1) {
    if (values[index] != null) {
      cumMain = values[index]!
      break
    }
  }

  return {
    ...series,
    cum_main: cumMain,
    values,
    price_values: series.price_values
      ? trimArraysToMinute(series.price_values, replayMinute)
      : undefined,
    avg_price_values: series.avg_price_values
      ? trimArraysToMinute(series.avg_price_values, replayMinute)
      : undefined,
    gray_values: series.gray_values
      ? trimArraysToMinute(series.gray_values, replayMinute)
      : undefined,
  }
}
