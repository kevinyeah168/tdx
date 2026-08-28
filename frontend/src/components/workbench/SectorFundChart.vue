<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { SectorFundFlowPayload } from '@/api/sectors'
import { alignValuesToTradingMinutes, TRADING_MINUTES, X_AXIS_TICKS } from '@/utils/tradingTimeline'
import { toYi } from '@/utils/format'

const props = defineProps<{
  payload: SectorFundFlowPayload | null
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const seriesData = computed(() => {
  const points = props.payload?.points ?? []
  const timeline = points.map((point) => point.minute)
  const values = points.map((point) => point.values.main?.cumulative ?? null)
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
      axisLabel: { formatter: (value: number) => `${toYi(value)}亿` },
    },
    series: [
      {
        name: '主力累计',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: seriesData.value,
        lineStyle: { width: 2, color: '#2563eb' },
        areaStyle: { opacity: 0.08, color: '#2563eb' },
      },
    ],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => `${toYi(value)}亿`,
    },
  })
}

watch(seriesData, renderChart, { deep: true })

onMounted(renderChart)
onBeforeUnmount(() => {
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
  height: 320px;
}
</style>
