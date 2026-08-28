<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { SectorFundFlowPayload } from '@/api/sectors'
import { alignValuesToTradingMinutes, TRADING_MINUTES, X_AXIS_TICKS } from '@/utils/tradingTimeline'
import { toYi } from '@/utils/format'

function previousTradingMinute(minute: string): string | null {
  const idx = TRADING_MINUTES.indexOf(minute)
  return idx > 0 ? TRADING_MINUTES[idx - 1]! : null
}

function buildTimeline(points: { minute: string }[]) {
  let timeline = points.map((point) => point.minute)
  if (timeline.length === 1) {
    const prev = previousTradingMinute(timeline[0]!)
    if (prev) timeline = [prev, ...timeline]
  }
  return timeline
}

const props = defineProps<{
  payload: SectorFundFlowPayload | null
  tiers?: string[]
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const activeTiers = computed(() => props.tiers?.length ? props.tiers : ['main'])

const palette: Record<string, string> = {
  main: '#2563eb',
  super: '#e03030',
  large: '#e86a20',
  medium: '#22c55e',
  small: '#64748b',
}

function seriesData(tier: string) {
  const points = props.payload?.points ?? []
  if (!points.length) return []
  const timeline = buildTimeline(points)
  let values = points.map((point) => point.values[tier]?.cumulative ?? null)
  if (values.length === 1 && values[0] != null && timeline.length > values.length) {
    values = [0, values[0]]
  }
  return alignValuesToTradingMinutes(timeline, values)
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  chart.setOption({
    grid: { left: 48, right: 16, top: 24, bottom: 28 },
    legend: { data: activeTiers.value },
    xAxis: {
      type: 'category',
      data: TRADING_MINUTES,
      axisLabel: {
        interval: (index: number) => X_AXIS_TICKS.includes(TRADING_MINUTES[index]),
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (value: number) => `${toYi(value)}亿` },
    },
    series: activeTiers.value.map((tier) => ({
      name: tier,
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: seriesData(tier),
      lineStyle: { width: 2, color: palette[tier] ?? '#2563eb' },
    })),
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => `${toYi(value)}亿`,
    },
  })
  chart.resize()
}

watch([() => props.payload, activeTiers], () => {
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
  <div ref="chartEl" class="fund-flow-chart" />
</template>

<style scoped>
.fund-flow-chart {
  width: 100%;
  flex: 1;
  min-height: 240px;
}
</style>
