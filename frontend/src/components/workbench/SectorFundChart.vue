<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { SectorFundFlowPayload } from '@/api/sectors'
import { fmtMoney, toYi } from '@/utils/format'
import { alignValuesToTradingMinutes, TRADING_MINUTES, X_AXIS_TICKS } from '@/utils/tradingTimeline'

const LINE_COLOR = '#2563eb'
const LABEL_UP = '#e03030'
const LABEL_DOWN = '#22a06b'

const props = defineProps<{
  payload: SectorFundFlowPayload | null
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

function lastNonNullIndex(values: (number | null)[]): number {
  for (let i = values.length - 1; i >= 0; i--) {
    if (values[i] != null) return i
  }
  return -1
}

const seriesData = computed(() => {
  const points = props.payload?.points ?? []
  const timeline = points.map((point) => point.minute)
  const values = points.map((point) => point.values.main?.cumulative ?? null)
  return alignValuesToTradingMinutes(timeline, values)
})

function symmetricAxisExtent(values: (number | null)[]): { min: number; max: number } {
  const nums = values.filter((value): value is number => value != null && Number.isFinite(value))
  if (!nums.length) {
    const unit = 1e8
    return { min: -unit, max: unit }
  }
  const maxAbs = Math.max(...nums.map((value) => Math.abs(value)))
  const pad = Math.max(maxAbs * 0.1, 5e7)
  const bound = maxAbs + pad
  return { min: -bound, max: bound }
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  const aligned = seriesData.value
  const tipIdx = lastNonNullIndex(aligned)
  const data = tipIdx >= 0 ? aligned.slice(0, tipIdx + 1) : []
  const lastValue = tipIdx >= 0 ? aligned[tipIdx] : null
  const extent = symmetricAxisExtent(aligned)
  const endColor = lastValue != null && lastValue < 0 ? LABEL_DOWN : LABEL_UP

  chart.setOption({
    grid: { left: 52, right: 88, top: 28, bottom: 28 },
    xAxis: {
      type: 'category',
      data: TRADING_MINUTES,
      axisLabel: {
        interval: (index: number) => X_AXIS_TICKS.includes(TRADING_MINUTES[index]),
      },
    },
    yAxis: {
      type: 'value',
      min: extent.min,
      max: extent.max,
      splitNumber: 4,
      axisLabel: { formatter: (value: number) => `${toYi(value)}亿` },
      splitLine: {
        lineStyle: { type: 'dashed', opacity: 0.35 },
      },
    },
    series: [
      {
        name: '明盘累计',
        type: 'line',
        smooth: 0.2,
        showSymbol: false,
        connectNulls: false,
        clip: true,
        data,
        lineStyle: { width: 2, color: LINE_COLOR },
        areaStyle: { opacity: 0.08, color: LINE_COLOR },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: 'rgba(148, 163, 184, 0.55)', width: 1 },
          data: [{ yAxis: 0 }],
        },
        endLabel: {
          show: tipIdx >= 0 && lastValue != null,
          formatter: () => fmtMoney(lastValue),
          color: endColor,
          fontSize: 11,
          fontWeight: 600,
          distance: 8,
          backgroundColor: 'rgba(255, 255, 255, 0.88)',
          padding: [2, 6, 2, 6],
          borderRadius: 4,
        },
        labelLayout: { hideOverlap: true },
      },
    ],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => fmtMoney(value),
    },
  })
  chart.resize()
}

watch(seriesData, () => {
  void nextTick(renderChart)
}, { deep: true })

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  void nextTick(() => {
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
  <div ref="chartEl" class="sector-fund-chart" />
</template>

<style scoped>
.sector-fund-chart {
  width: 100%;
  flex: 1;
  min-height: 240px;
}
</style>
