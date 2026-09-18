<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useChartTheme } from '@/composables/useChartTheme'
import { useThemeStore } from '@/stores/themeStore'
import type { FlowSeries } from '@/types/board'
import { seriesColor } from '@/utils/chartColors'
import { fmtMoney, toYi } from '@/utils/format'

const END_LABEL_MAX = 10

const props = defineProps<{
  series: FlowSeries[]
  dateTimeline: string[]
  cursorIndex?: number | null
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
const themeStore = useThemeStore()
const { colors } = useChartTheme()

const xLabels = computed(() =>
  props.dateTimeline.map((date) => {
    const [, month, day] = date.split('-')
    return `${month}-${day}`
  }),
)

function shortLabel(name: string, max = 8): string {
  const label = name.replace(/\u0000/g, '').trim()
  return label.length > max ? `${label.slice(0, max)}…` : label
}

function lastNonNullIndex(values: (number | null)[]): number {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index] != null && Number.isFinite(values[index]!)) return index
  }
  return -1
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

function buildAlignedData(values: (number | null)[], timelineLength: number) {
  const valuesYi = Array.from({ length: timelineLength }, (_, index) => {
    const value = values[index]
    return value == null || !Number.isFinite(value) ? null : toYi(value)
  })
  const tipIdx = lastNonNullIndex(valuesYi)
  return {
    data: valuesYi,
    tipIdx,
    lastYi: tipIdx >= 0 ? valuesYi[tipIdx] : null,
  }
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  const list = props.series
  const c = colors.value
  const cursorIndex =
    props.cursorIndex != null && props.cursorIndex >= 0 ? props.cursorIndex : null
  const showEndLabels = list.length <= END_LABEL_MAX
  const gridRight = showEndLabels
    ? Math.max(132, Math.min(220, 92 + list.length * 14))
    : 24

  const visibleNums: number[] = []
  const chartSeries: echarts.SeriesOption[] = list.map((item) => {
    const color = seriesColor(list, item, item.symbol ? 'stock' : 'sector')
    const { data, tipIdx, lastYi } = buildAlignedData(item.values || [], props.dateTimeline.length)
    for (const value of data) {
      if (value != null && Number.isFinite(value)) visibleNums.push(value)
    }

    return {
      id: item.id,
      name: item.name,
      type: 'line' as const,
      showSymbol: tipIdx >= 0,
      symbolSize: (_value: number | null, params: { dataIndex?: number }) => {
        if (cursorIndex != null && params.dataIndex === cursorIndex) return 7
        if (params.dataIndex === tipIdx) return 4
        return 0
      },
      connectNulls: false,
      smooth: 0.2,
      clip: true,
      data,
      lineStyle: { width: 2, color },
      itemStyle: { color },
      emphasis: { focus: 'series' as const },
      endLabel: showEndLabels
        ? {
            show: tipIdx >= 0,
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
            backgroundColor: themeStore.isDark
              ? 'rgba(15, 23, 42, 0.72)'
              : 'rgba(255, 255, 255, 0.88)',
            padding: [2, 5, 2, 5],
            borderRadius: 4,
          }
        : { show: false },
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
    }
  })

  const extent = fundAxisExtentYi(visibleNums)

  if (chartSeries.length) {
    chartSeries[0]!.markLine = {
      symbol: 'none',
      silent: true,
      lineStyle: { color: 'rgba(148, 163, 184, 0.55)', width: 1 },
      data: [{ yAxis: 0 }],
    }
    if (cursorIndex != null) {
      chartSeries[0]!.markLine.data = [
        { yAxis: 0 },
        {
          xAxis: cursorIndex,
          lineStyle: {
            color: themeStore.isDark ? 'rgba(96, 165, 250, 0.85)' : 'rgba(37, 99, 235, 0.75)',
            type: 'dashed',
            width: 1.5,
          },
          label: { show: false },
        },
      ]
    }
  }

  chart.setOption(
    {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 52, right: gridRight, top: 20, bottom: 32 },
      legend: { show: false },
      xAxis: {
        type: 'category',
        data: xLabels.value,
        boundaryGap: false,
        axisLabel: { color: c.axis, fontSize: 10, interval: 0 },
        axisLine: { lineStyle: { color: c.axisLine } },
        axisTick: { alignWithLabel: true },
      },
      yAxis: {
        type: 'value',
        name: '亿',
        nameTextStyle: { color: c.axis, fontSize: 10 },
        axisLabel: {
          color: c.axis,
          fontSize: 10,
          formatter: (value: number) => Number(value).toFixed(Math.abs(value) >= 100 ? 0 : 1),
        },
        min: extent?.min,
        max: extent?.max,
        splitLine: { lineStyle: { color: c.splitLine, type: 'dashed', opacity: 0.35 } },
      },
      tooltip: {
        trigger: 'axis',
        confine: true,
        backgroundColor: c.tooltipBg,
        borderColor: c.tooltipBorder,
        textStyle: { color: c.tooltipText, fontSize: 12 },
        formatter: (params: unknown) => {
          if (!Array.isArray(params) || !params.length) return ''
          const axisIndex = Number(params[0]?.dataIndex ?? 0)
          const fullDate = props.dateTimeline[axisIndex] ?? ''
          const lines = params
            .filter((entry) => entry.value != null && entry.value !== '')
            .sort((a, b) => Number(b.value) - Number(a.value))
            .slice(0, 12)
            .map(
              (entry) =>
                `${entry.marker}${entry.seriesName}: ${fmtMoney(Number(entry.value) * 1e8)}`,
            )
          const hidden = params.length - lines.length
          const suffix = hidden > 0 ? `<br/>… 另有 ${hidden} 条` : ''
          return [fullDate, ...lines].join('<br/>') + suffix
        },
      },
      series: chartSeries,
    },
    true,
  )
  chart.resize()
}

watch(
  [() => props.series, () => props.dateTimeline, () => props.cursorIndex, colors, () => themeStore.isDark],
  () => {
    void nextTick(renderChart)
  },
  { deep: true },
)

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
  <div ref="chartEl" class="cycle-trend-chart" />
</template>

<style scoped>
.cycle-trend-chart {
  width: 100%;
  height: 100%;
  min-height: 0;
}
</style>
