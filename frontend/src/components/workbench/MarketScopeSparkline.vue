<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useChartTheme } from '@/composables/useChartTheme'
import { toYi } from '@/utils/format'

const props = defineProps<{
  values: (number | null)[]
  color: string
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
const { colors } = useChartTheme()

const hasData = computed(() => props.values.some((value) => value != null && Number.isFinite(value)))

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  const nums = props.values
    .filter((value): value is number => value != null && Number.isFinite(value))
    .map((value) => toYi(value))

  if (!nums.length) {
    chart.clear()
    return
  }

  const min = Math.min(...nums, 0)
  const max = Math.max(...nums, 0)
  const pad = Math.max((max - min) * 0.12, 0.3)

  chart.setOption(
    {
      animation: false,
      grid: { left: 1, right: 1, top: 2, bottom: 1 },
      xAxis: { type: 'category', show: false, data: props.values.map((_, index) => index) },
      yAxis: {
        type: 'value',
        show: false,
        min: min - pad,
        max: max + pad,
      },
      series: [
        {
          type: 'line',
          showSymbol: false,
          smooth: 0.2,
          data: props.values.map((value) =>
            value == null || !Number.isFinite(value) ? null : toYi(value),
          ),
          lineStyle: { width: 1.5, color: props.color },
          areaStyle: { opacity: 0.14, color: props.color },
        },
        {
          type: 'line',
          markLine: {
            symbol: 'none',
            silent: true,
            lineStyle: { color: colors.value.splitLine, width: 1, opacity: 0.45 },
            data: [{ yAxis: 0 }],
          },
          data: [],
        },
      ],
    },
    true,
  )
  chart.resize()
}

watch(() => props.values, () => void nextTick(renderChart), { deep: true })

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
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="chartEl" class="market-scope-sparkline" :class="{ 'is-empty': !hasData }" />
</template>

<style scoped>
.market-scope-sparkline {
  width: 100%;
  height: 100%;
  min-height: 68px;
}

.market-scope-sparkline.is-empty {
  opacity: 0.35;
}
</style>
