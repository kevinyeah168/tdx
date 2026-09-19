<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useChartTheme } from '@/composables/useChartTheme'
import { useThemeStore } from '@/stores/themeStore'
import type { FlowSeries } from '@/types/board'
import { seriesColor } from '@/utils/chartColors'
import { fmtMoney, toYi } from '@/utils/format'
import { alignValuesToTradingMinutes, TRADING_MINUTES, X_AXIS_TICKS } from '@/utils/tradingTimeline'

const MAIN_COLOR = '#2563eb'
const GRAY_COLOR_LIGHT = '#9333ea'
const GRAY_COLOR_DARK = '#c084fc'

const props = defineProps<{
  mode: 'multi' | 'solo'
  series: FlowSeries[]
  soloSeries?: FlowSeries | null
}>()

const emit = defineEmits<{
  enterSolo: [symbol: string]
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
const themeStore = useThemeStore()
const { colors } = useChartTheme()

const timeline = computed(() => TRADING_MINUTES)

function lastNonNullIndex(values: (number | null)[]): number {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index] != null) return index
  }
  return -1
}

function shortLabel(name: string, max = 8): string {
  const label = name.replace(/\u0000/g, '').trim()
  return label.length > max ? `${label.slice(0, max)}…` : label
}

function fundAxisExtentYi(nums: number[]): { min: number; max: number } | null {
  if (!nums.length) return null
  const min = Math.min(...nums)
  const max = Math.max(...nums)
  if (min === max) {
    const pad = Math.max(Math.abs(min) * 0.05, 0.5)
    return { min: min - pad, max: max + pad }
  }
  const pad = Math.max((max - min) * 0.08, 0.5)
  return { min: min - pad, max: max + pad }
}

function collectFundYi(series: FlowSeries, includeGray = false): number[] {
  const nums: number[] = []
  const aligned = alignValuesToTradingMinutes(timeline.value, series.values || [])
  for (const value of aligned) {
    if (value != null && Number.isFinite(value)) nums.push(toYi(value))
  }
  if (includeGray && series.gray_values?.length) {
    const grayAligned = alignValuesToTradingMinutes(timeline.value, series.gray_values)
    for (const value of grayAligned) {
      if (value != null && Number.isFinite(value)) nums.push(toYi(value))
    }
  }
  return nums
}

function buildMultiSeries(list: FlowSeries[]) {
  const gridRight = Math.max(132, Math.min(240, 88 + list.length * 12))
  const extent = fundAxisExtentYi(
    list.flatMap((item) => collectFundYi(item)),
  )

  const chartSeries = list.map((item) => {
    const color = seriesColor(list, item, 'stock')
    const aligned = alignValuesToTradingMinutes(timeline.value, item.values || [])
    const valuesYi = aligned.map((value) => (value == null ? null : toYi(value)))
    const tipIdx = lastNonNullIndex(valuesYi)
    const data = tipIdx >= 0 ? valuesYi.slice(0, tipIdx + 1) : []
    const lastYi = tipIdx >= 0 ? valuesYi[tipIdx] : null

    return {
      id: item.id,
      name: item.name,
      type: 'line' as const,
      yAxisIndex: 0,
      showSymbol: false,
      triggerLineEvent: true,
      connectNulls: false,
      smooth: 0.15,
      clip: true,
      data,
      z: 2,
      lineStyle: { width: 2.2, opacity: 1, color },
      itemStyle: { color },
      endLabel: {
        show: tipIdx >= 0,
        triggerEvent: true,
        formatter: () => {
          const money =
            lastYi != null && Number.isFinite(lastYi)
              ? fmtMoney(lastYi * 1e8)
              : fmtMoney(item.cum_main)
          return `${shortLabel(item.name)} ${money}`
        },
        color,
        fontSize: 10,
        fontWeight: 600,
        distance: 6,
        backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.88)',
        padding: [2, 5, 2, 5],
        borderRadius: 4,
      },
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
    }
  })

  return { chartSeries, gridRight, extent, showPrice: false }
}

function buildSoloSeries(item: FlowSeries) {
  const c = colors.value
  const grayColor = themeStore.isDark ? GRAY_COLOR_DARK : GRAY_COLOR_LIGHT
  const gridRight = 168
  const extent = fundAxisExtentYi(collectFundYi(item, true))
  const chartSeries: echarts.SeriesOption[] = []

  const mainAligned = alignValuesToTradingMinutes(timeline.value, item.values || [])
  const mainYi = mainAligned.map((value) => (value == null ? null : toYi(value)))
  const mainTipIdx = lastNonNullIndex(mainYi)
  const mainData = mainTipIdx >= 0 ? mainYi.slice(0, mainTipIdx + 1) : []
  const mainLastYi = mainTipIdx >= 0 ? mainYi[mainTipIdx] : null

  chartSeries.push({
    id: item.id,
    name: '明盘',
    type: 'line',
    yAxisIndex: 0,
    showSymbol: false,
    triggerLineEvent: true,
    connectNulls: false,
    smooth: 0.15,
    clip: true,
    data: mainData,
    z: 10,
    lineStyle: { width: 2.5, color: MAIN_COLOR },
    itemStyle: { color: MAIN_COLOR },
    endLabel: {
      show: mainTipIdx >= 0,
      formatter: () =>
        mainLastYi != null && Number.isFinite(mainLastYi)
          ? `明盘 ${fmtMoney(mainLastYi * 1e8)}`
          : `明盘 ${fmtMoney(item.cum_main)}`,
      color: MAIN_COLOR,
      fontSize: 11,
      fontWeight: 700,
      distance: 6,
      backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.88)',
      padding: [2, 6, 2, 6],
      borderRadius: 4,
    },
    labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
  })

  if (item.gray_values?.length) {
    const grayAligned = alignValuesToTradingMinutes(timeline.value, item.gray_values)
    const grayYi = grayAligned.map((value) => (value == null ? null : toYi(value)))
    const grayTipIdx = lastNonNullIndex(grayYi)
    const grayData = grayTipIdx >= 0 ? grayYi.slice(0, grayTipIdx + 1) : []
    const grayLastYi = grayTipIdx >= 0 ? grayYi[grayTipIdx] : null
    chartSeries.push({
      id: `__gray__:${item.id}`,
      name: '暗盘',
      type: 'line',
      yAxisIndex: 0,
      showSymbol: false,
      triggerLineEvent: false,
      connectNulls: false,
      smooth: 0.15,
      clip: true,
      data: grayData,
      z: 9,
      silent: true,
      lineStyle: { width: 2, color: grayColor },
      itemStyle: { color: grayColor },
      endLabel: {
        show: grayTipIdx >= 0,
        formatter: () =>
          grayLastYi != null && Number.isFinite(grayLastYi)
            ? `暗盘 ${fmtMoney(grayLastYi * 1e8)}`
            : '暗盘',
        color: grayColor,
        fontSize: 10,
        fontWeight: 600,
        distance: 6,
        backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.88)',
        padding: [2, 5, 2, 5],
        borderRadius: 4,
      },
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
    })
  }

  if (item.avg_price_values?.length) {
    const avgAligned = alignValuesToTradingMinutes(timeline.value, item.avg_price_values)
    const avgTipIdx = lastNonNullIndex(avgAligned)
    const avgData = avgAligned.map((value, index) => (index <= avgTipIdx ? value : null))
    const avgLast = avgTipIdx >= 0 ? avgAligned[avgTipIdx] : null
    const avgColor = themeStore.isDark ? '#fbbf24' : '#d97706'
    chartSeries.push({
      id: `__avg__:${item.id}`,
      name: '均价',
      type: 'line',
      yAxisIndex: 1,
      showSymbol: false,
      triggerLineEvent: false,
      connectNulls: false,
      smooth: 0.15,
      clip: true,
      data: avgData,
      z: 12,
      silent: true,
      lineStyle: { width: 2, color: avgColor },
      itemStyle: { color: avgColor },
      endLabel: {
        show: avgTipIdx >= 0 && avgLast != null,
        formatter: () => `均价 ${Number(avgLast).toFixed(2)}`,
        color: avgColor,
        fontSize: 10,
        fontWeight: 600,
        distance: 6,
        backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.88)',
        padding: [2, 5, 2, 5],
        borderRadius: 4,
      },
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
    })
  }

  if (item.price_values?.length) {
    const priceAligned = alignValuesToTradingMinutes(timeline.value, item.price_values)
    const priceTipIdx = lastNonNullIndex(priceAligned)
    const priceData = priceAligned.map((value, index) => (index <= priceTipIdx ? value : null))
    const priceLast = priceTipIdx >= 0 ? priceAligned[priceTipIdx] : null
    const priceColor = themeStore.isDark ? '#94a3b8' : '#64748b'
    chartSeries.push({
      id: `__price__:${item.id}`,
      name: '价格',
      type: 'line',
      yAxisIndex: 1,
      showSymbol: false,
      triggerLineEvent: false,
      connectNulls: false,
      smooth: 0.15,
      clip: true,
      data: priceData,
      z: 11,
      silent: true,
      lineStyle: { width: 1.8, type: 'dashed', color: priceColor },
      itemStyle: { color: priceColor },
      endLabel: {
        show: priceTipIdx >= 0 && priceLast != null,
        formatter: () => `价格 ${Number(priceLast).toFixed(2)}`,
        color: priceColor,
        fontSize: 10,
        fontWeight: 600,
        distance: 6,
        backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.88)',
        padding: [2, 5, 2, 5],
        borderRadius: 4,
      },
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
    })
  }

  const yAxis = [
    {
      type: 'value',
      min: extent?.min,
      max: extent?.max,
      axisLabel: {
        color: c.axis,
        fontSize: 10,
        formatter: (value: number) => Number(value).toFixed(Math.abs(value) >= 100 ? 0 : 1),
      },
      name: '亿',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.splitLine, type: 'dashed', opacity: 0.35 } },
    },
    {
      type: 'value',
      scale: true,
      position: 'right',
      alignTicks: false,
      axisLabel: { color: c.axis, fontSize: 10, formatter: (value: number) => value.toFixed(2) },
      name: '价格',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      splitLine: { show: false },
    },
  ]

  return { chartSeries, gridRight, extent, showPrice: true, yAxis }
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  const c = colors.value
  let chartSeries: echarts.SeriesOption[] = []
  let gridRight = 132
  let extent: { min: number; max: number } | null = null
  let showPrice = false
  let yAxis: object[] | undefined

  if (props.mode === 'solo' && props.soloSeries) {
    const solo = buildSoloSeries(props.soloSeries)
    chartSeries = solo.chartSeries as echarts.SeriesOption[]
    gridRight = solo.gridRight
    extent = solo.extent
    showPrice = solo.showPrice
    yAxis = solo.yAxis
  } else {
    const list = props.series
    if (!list.length) {
      chart.clear()
      return
    }
    const multi = buildMultiSeries(list)
    chartSeries = multi.chartSeries as echarts.SeriesOption[]
    gridRight = multi.gridRight
    extent = multi.extent
    showPrice = multi.showPrice
  }

  const yAxisFinal =
    yAxis ??
    [
      {
        type: 'value',
        min: extent?.min,
        max: extent?.max,
        axisLabel: {
          color: c.axis,
          fontSize: 10,
          formatter: (value: number) => Number(value).toFixed(Math.abs(value) >= 100 ? 0 : 1),
        },
        name: '亿',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        splitLine: { lineStyle: { color: c.splitLine, type: 'dashed', opacity: 0.35 } },
      },
    ]

  chart.setOption(
    {
      backgroundColor: 'transparent',
      animation: false,
      grid: {
        left: 48,
        right: showPrice ? gridRight + 40 : gridRight,
        top: 28,
        bottom: 28,
      },
      legend: { show: false },
      xAxis: {
        type: 'category',
        data: TRADING_MINUTES,
        boundaryGap: false,
        axisLabel: {
          color: c.axis,
          fontSize: 10,
          interval: (index: number) => X_AXIS_TICKS.includes(TRADING_MINUTES[index]),
        },
        axisLine: { lineStyle: { color: c.axisLine } },
      },
      yAxis: yAxisFinal,
      tooltip: {
        trigger: 'axis',
        backgroundColor: c.tooltipBg,
        borderColor: c.tooltipBorder,
        textStyle: { color: c.tooltipText, fontSize: 12 },
        formatter: (params: unknown) => {
          if (!Array.isArray(params) || !params.length) return ''
          const axisLabel = String(params[0]?.axisValue ?? '')
          const lines = [...params]
            .filter((entry) => entry.value != null && entry.value !== '')
            .map((entry) => {
              const name = String(entry.seriesName ?? '')
              if (name === '均价' || name === '价格') {
                return `${entry.marker}${name}: ${Number(entry.value).toFixed(2)}`
              }
              return `${entry.marker}${name}: ${fmtMoney(Number(entry.value) * 1e8)}`
            })
          return [axisLabel, ...lines].join('<br/>')
        },
      },
      series: chartSeries,
    },
    true,
  )
  chart.resize()
}

function resolveClickedSymbol(params: {
  componentType?: string
  seriesId?: string | number
  seriesName?: string
  dataIndex?: number
}): string | null {
  if (params.componentType !== 'series') return null
  if (params.seriesId != null && params.seriesId !== '') {
    const id = String(params.seriesId)
    if (!id.startsWith('__')) return id
  }
  if (params.seriesName) {
    const byName = props.series.find((item) => item.name === params.seriesName)
    if (byName) return byName.id
    const byLabel = props.series.find((item) => shortLabel(item.name) === params.seriesName)
    if (byLabel) return byLabel.id
  }
  if (typeof params.dataIndex === 'number' && params.dataIndex >= 0) {
    const fromIndex = props.series[params.dataIndex]
    if (fromIndex) return fromIndex.id
  }
  return null
}

function onChartClick(params: {
  componentType?: string
  seriesId?: string | number
  seriesName?: string
  dataIndex?: number
}) {
  if (props.mode !== 'multi') return
  const symbol = resolveClickedSymbol(params)
  if (symbol) emit('enterSolo', symbol)
}

function bindEvents() {
  if (!chart) return
  chart.off('click')
  chart.on('click', onChartClick)
}

watch(
  [() => props.mode, () => props.series, () => props.soloSeries, colors, () => themeStore.isDark],
  () => {
    void nextTick(renderChart)
  },
  { deep: true },
)

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  void nextTick(() => {
    bindEvents()
    renderChart()
    if (chartEl.value) {
      resizeObserver = new ResizeObserver(() => chart?.resize())
      resizeObserver.observe(chartEl.value)
    }
  })
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="chartEl" class="stock-multi-chart" />
</template>

<style scoped>
.stock-multi-chart {
  width: 100%;
  flex: 1;
  min-height: 320px;
}
</style>
