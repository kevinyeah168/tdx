<script setup lang="ts">
import * as echarts from 'echarts'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ChartEmptyState from '@/components/chart/ChartEmptyState.vue'
import { useChartTheme } from '@/composables/useChartTheme'
import { useThemeStore } from '@/stores/themeStore'
import { useBoardStore } from '@/stores/boardStore'
import { seriesColor } from '@/utils/chartColors'
import { fmtMoney, toYi } from '@/utils/format'
import {
  alignValuesToTradingMinutes,
  countNonNullValues,
  TRADING_MINUTES,
  X_AXIS_TICKS,
} from '@/utils/tradingTimeline'
import type { FlowSeries } from '@/types/board'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const themeStore = useThemeStore()
const { board, highlightedSector, highlightedStock } = storeToRefs(boardStore)
const { colors } = useChartTheme()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const viewDate = computed(() =>
  props.mode === 'stock' ? board.value.stock_view_date : board.value.sector_view_date,
)

const sourceTimeline = computed(() =>
  props.mode === 'stock' ? board.value.stock_timeline : board.value.timeline,
)

const seriesList = computed<FlowSeries[]>(() =>
  props.mode === 'stock' ? board.value.stock_series : board.value.sector_series,
)

const highlighted = computed(() =>
  props.mode === 'stock' ? highlightedStock.value : highlightedSector.value,
)

const hasChartData = computed(() => {
  const tl = sourceTimeline.value || []
  return seriesList.value.some((s) => {
    const aligned = alignValuesToTradingMinutes(tl, s.values || [])
    return countNonNullValues(aligned) >= 2
  })
})

const showEmpty = computed(() => {
  const session = board.value.trading_session
  const vd = viewDate.value
  const today = session?.tradeDate
  if (vd === today && session?.marketStatus === 'pre_open') return true
  if (!seriesList.value.length) return true
  return !hasChartData.value
})

const emptyTitle = computed(() => {
  const session = board.value.trading_session
  if (session?.marketStatus === 'pre_open') return '尚未开盘'
  if (session?.marketStatus === 'non_trading_day') return '非交易日'
  return '暂无分时数据'
})

const emptyMessage = computed(() => {
  const session = board.value.trading_session
  if (session?.message) return session.message
  if (viewDate.value !== session?.tradeDate) return '该交易日暂无采样数据'
  return '今日尚未开盘，数据在交易日 09:31 开始实时更新'
})

function shortName(name: string, max = 8): string {
  return name.length > max ? `${name.slice(0, max)}…` : name
}

function endLabelStyle(color: string, emphasized: boolean, list: FlowSeries[]) {
  return {
    show: true,
    formatter: (params: { seriesName?: string; value?: number | null }) => {
      const item = list.find((s) => s.name === params.seriesName || s.id === params.seriesName)
      const label = item?.name || params.seriesName || ''
      const money = item ? fmtMoney(item.cum_main) : fmtMoney((params.value ?? 0) * 1e8)
      return `${shortName(label)} ${money}`
    },
    color,
    fontSize: emphasized ? 11 : 10,
    fontWeight: emphasized ? 700 : 500,
    distance: 6,
    backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.88)',
    padding: [2, 5, 2, 5],
    borderRadius: 4,
  }
}

function lastNonNullIndex(values: (number | null)[]): number {
  for (let i = values.length - 1; i >= 0; i--) {
    if (values[i] != null) return i
  }
  return -1
}

function baseAxis(gridRight: number) {
  const c = colors.value
  return {
    grid: { left: 48, right: gridRight, top: 32, bottom: 32 },
    xAxis: {
      type: 'category' as const,
      data: TRADING_MINUTES,
      boundaryGap: false,
      axisLabel: {
        color: c.axis,
        fontSize: 10,
        hideOverlap: false,
        interval: 0,
        formatter: (value: string) => (X_AXIS_TICKS.includes(value) ? value : ''),
      },
      axisLine: { lineStyle: { color: c.axisLine } },
      axisTick: { show: false },
    },
    yAxis: {
      scale: true,
      axisLabel: { color: c.axis, formatter: (v: number) => `${v}`, fontSize: 10 },
      name: '亿',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.splitLine } },
    },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: c.tooltipBg,
      borderColor: c.tooltipBorder,
      textStyle: { color: c.tooltipText, fontSize: 12 },
      valueFormatter: (v: unknown) =>
        v == null ? '—' : `${Number(v).toFixed(2)}亿`,
    },
  }
}

function buildSeries(list: FlowSeries[], hl: string | null, tl: string[]) {
  const visible = list.filter((s) => !hl || hl === s.id)
  const gridRight = Math.max(148, Math.min(240, 96 + visible.length * 14))

  const series = list.map((s) => {
    const active = !hl || hl === s.id
    const color = seriesColor(list, s, props.mode)
    const aligned = alignValuesToTradingMinutes(tl, s.values || [])
    const valuesYi = aligned.map((v) => (v == null ? null : toYi(v)))
    const tipIdx = lastNonNullIndex(valuesYi)
    // Truncate trailing nulls so ECharts endLabel sits on the last captured point
    const data = tipIdx >= 0 ? valuesYi.slice(0, tipIdx + 1) : []

    return {
      id: s.id,
      name: s.name,
      type: 'line' as const,
      showSymbol: false,
      connectNulls: false,
      smooth: 0.15,
      clip: false,
      data,
      z: active && hl ? 10 : 2,
      lineStyle: {
        width: hl === s.id ? 2.5 : active ? 1.6 : 1,
        opacity: active ? 1 : 0.12,
        color,
        shadowBlur: hl === s.id ? 8 : 0,
        shadowColor: hl === s.id ? color : undefined,
      },
      itemStyle: { color },
      endLabel:
        active && tipIdx >= 0
          ? endLabelStyle(color, hl === s.id, list)
          : { show: false },
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
    }
  })

  return { series, gridRight }
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  if (showEmpty.value) {
    chart.clear()
    return
  }

  const tl = sourceTimeline.value || []
  const list = seriesList.value || []
  const { series, gridRight } = buildSeries(list, highlighted.value, tl)

  chart.setOption(
    {
      backgroundColor: 'transparent',
      animation: false,
      ...baseAxis(gridRight),
      series,
    },
    true,
  )
}

function resizeChart() {
  chart?.resize()
}

watch(
  [sourceTimeline, seriesList, highlighted, showEmpty, () => props.mode, colors, () => themeStore.isDark],
  async () => {
    await nextTick()
    renderChart()
  },
  { deep: true },
)

onMounted(() => {
  renderChart()
  window.addEventListener('resize', resizeChart)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
  chart = null
})

defineExpose({ renderChart, resizeChart })
</script>

<template>
  <section class="panel-card flex min-h-0 flex-1 flex-col p-2.5">
    <div class="relative min-h-[420px] flex-1 w-full">
      <div ref="chartEl" class="absolute inset-0" />
      <ChartEmptyState
        v-if="showEmpty"
        :title="emptyTitle"
        :message="emptyMessage"
      />
    </div>
  </section>
</template>
