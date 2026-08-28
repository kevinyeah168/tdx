<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { StockBarsPayload } from '@/api/stocks'

const props = defineProps<{
  payload: StockBarsPayload | null
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const labels = computed(() => props.payload?.bars.map((bar) => bar.timestamp.slice(0, 10)) ?? [])
const closes = computed(() => props.payload?.bars.map((bar) => bar.close) ?? [])

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  chart.setOption({
    grid: { left: 48, right: 16, top: 24, bottom: 28 },
    xAxis: { type: 'category', data: labels.value },
    yAxis: { type: 'value', scale: true },
    series: [
      {
        name: '收盘价',
        type: 'line',
        smooth: false,
        showSymbol: false,
        data: closes.value,
        lineStyle: { width: 2, color: '#e03030' },
      },
    ],
    tooltip: { trigger: 'axis' },
  })
}

watch([labels, closes], renderChart, { deep: true })

onMounted(renderChart)
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="chartEl" class="stock-bars-chart" />
</template>

<style scoped>
.stock-bars-chart {
  width: 100%;
  height: 280px;
}
</style>
