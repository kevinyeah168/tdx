<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { StockIntradayPoint } from '@/api/stocks'
import { fmtPct } from '@/utils/format'
import { alignValuesToTradingMinutes, TRADING_MINUTES, X_AXIS_TICKS } from '@/utils/tradingTimeline'

const props = defineProps<{
  points: StockIntradayPoint[]
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const seriesData = computed(() => {
  const timeline = props.points.map((point) => point.minute)
  const values = props.points.map((point) => point.change_pct ?? null)
  return alignValuesToTradingMinutes(timeline, values)
})

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  chart.setOption({
    grid: { left: 48, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: 'category',
      data: TRADING_MINUTES,
      axisLabel: {
        interval: (index: number) => X_AXIS_TICKS.includes(TRADING_MINUTES[index]),
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { formatter: (value: number) => fmtPct(value) },
      splitLine: {
        lineStyle: { type: 'dashed', opacity: 0.35 },
      },
    },
    series: [
      {
        name: '涨跌幅',
        type: 'line',
        smooth: 0.15,
        showSymbol: false,
        connectNulls: false,
        data: seriesData.value,
        lineStyle: { width: 2, color: '#2563eb' },
        areaStyle: { opacity: 0.06, color: '#2563eb' },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: 'rgba(148, 163, 184, 0.55)', width: 1 },
          data: [{ yAxis: 0 }],
        },
      },
    ],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => fmtPct(value),
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
  <div ref="chartEl" class="stock-intraday-chart" />
</template>

<style scoped>
.stock-intraday-chart {
  width: 100%;
  flex: 1;
  min-height: 200px;
}
</style>
