<script setup lang="ts">
import * as echarts from 'echarts'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ChartEmptyState from '@/components/chart/ChartEmptyState.vue'
import { useChartTheme } from '@/composables/useChartTheme'
import { useThemeStore } from '@/stores/themeStore'
import { useBoardStore } from '@/stores/boardStore'
import { seriesColor } from '@/utils/chartColors'
import { fmtMoney, fmtPct, fmtSectorSeriesLabel, toYi } from '@/utils/format'
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

const soloStockSeries = computed(() => {
  if (props.mode !== 'stock' || !highlighted.value) return null
  return seriesList.value.find((item) => item.id === highlighted.value) ?? null
})

const showPriceOverlay = computed(() => {
  const solo = soloStockSeries.value
  return Boolean(solo?.price_values?.some((value) => value != null))
})

const PRICE_SERIES_PREFIX = '__price__:'

const hasChartData = computed(() => {
  const tl = sourceTimeline.value || []
  return seriesList.value.some((s) => {
    const aligned = alignValuesToTradingMinutes(tl, s.values || [])
    return countNonNullValues(aligned) >= 1
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
  if (session?.marketStatus === 'open') return '加载中'
  return '暂无分时数据'
})

const emptyMessage = computed(() => {
  const session = board.value.trading_session
  if (session?.message) return session.message
  if (viewDate.value !== session?.tradeDate) return '该交易日暂无采样数据'
  return '今日尚未开盘，数据在交易日 09:31 开始实时更新'
})

function seriesLabel(item: FlowSeries): string {
  if (props.mode === 'sector') return fmtSectorSeriesLabel(item)
  return item.name
}

function shortLabel(item: FlowSeries, max = 10): string {
  const label = seriesLabel(item)
  return label.length > max ? `${label.slice(0, max)}…` : label
}

function endLabelStyle(color: string, emphasized: boolean, list: FlowSeries[]) {
  return {
    show: true,
    formatter: (params: { seriesName?: string; value?: number | null }) => {
      const item = list.find((s) => s.id === params.seriesName)
      const label = item ? shortLabel(item) : params.seriesName || ''
      const money = item ? fmtMoney(item.cum_main) : fmtMoney((params.value ?? 0) * 1e8)
      return `${label} ${money}`
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

function chartTipMaxHeight(): number {
  const h = chartEl.value?.clientHeight ?? 0
  // 最大高度与图表可视高度一致，优先一次展全
  if (h >= 120) return h
  return Math.max(320, Math.min(window.innerHeight - 32, 720))
}

function tooltipNearMouse(
  point: number[],
  _params: unknown,
  _dom: HTMLElement,
  _rect: { x: number; y: number; width: number; height: number },
  size: { contentSize: number[]; viewSize: number[] },
): number[] {
  // 返回图表内坐标；appendTo body 时由 ECharts 换算到页面
  const [tw, th] = size.contentSize
  const [vw, vh] = size.viewSize
  const gap = 16
  let x = point[0] + gap
  let y = point[1] - 12

  if (x + tw > vw - 4) x = point[0] - tw - gap
  if (x < 4) x = 4

  // 高度接近图表时贴顶，避免裁切；否则跟随鼠标并夹在图表内
  if (th >= vh * 0.82) {
    y = 2
  } else {
    if (y + th > vh - 4) y = vh - th - 4
    if (y < 2) y = 2
  }

  return [x, y]
}

function baseAxis(gridRight: number, list: FlowSeries[], showPrice = false) {
  const c = colors.value
  const seriesCount = seriesList.value.length
  const tipMaxH = chartTipMaxHeight()
  const dense = seriesCount > 10
  const yAxis: object[] = [
    {
      scale: true,
      axisLabel: { color: c.axis, formatter: (v: number) => `${v}`, fontSize: 10 },
      name: '亿',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: c.splitLine } },
    },
  ]
  if (showPrice) {
    yAxis.push({
      scale: true,
      position: 'right',
      axisLabel: { color: c.axis, formatter: (v: number) => v.toFixed(2), fontSize: 10 },
      name: '价格',
      nameTextStyle: { color: c.axis, fontSize: 10 },
      splitLine: { show: false },
    })
  }
  return {
    grid: { left: 48, right: showPrice ? gridRight + 40 : gridRight, top: 32, bottom: 32 },
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
    yAxis,
    tooltip: {
      trigger: 'axis' as const,
      appendTo: 'body' as const,
      className: 'fund-flow-tooltip',
      order: 'valueDesc' as const,
      position: tooltipNearMouse,
      backgroundColor: c.tooltipBg,
      borderColor: c.tooltipBorder,
      borderWidth: 1,
      padding: dense ? [6, 10] : [8, 12],
      textStyle: {
        color: c.tooltipText,
        fontSize: dense ? 11 : 12,
        lineHeight: dense ? 16 : 18,
      },
      extraCssText: [
        `max-height:${tipMaxH}px`,
        'overflow-y:auto',
        'pointer-events:none',
        'box-shadow:0 8px 28px rgba(15,23,42,0.18)',
        'border-radius:8px',
        'z-index:4000',
      ].join(';'),
      formatter: (params: unknown) => {
        if (!Array.isArray(params) || !params.length) return ''
        const axisLabel = String(params[0]?.axisValue ?? '')
        const lines = [...params]
          .filter((entry) => entry.value != null && entry.value !== '')
          .sort((a, b) => Number(b.value) - Number(a.value))
          .map((entry) => {
            const seriesKey = String(entry.seriesId ?? entry.seriesName ?? '')
            if (seriesKey.startsWith(PRICE_SERIES_PREFIX)) {
              const solo = soloStockSeries.value
              const pct = solo?.change_pct
              const pctText = pct != null ? ` (${fmtPct(pct)})` : ''
              return `${entry.marker}价格: ${Number(entry.value).toFixed(2)}${pctText}`
            }
            const item = list.find((s) => s.id === entry.seriesName)
            const label = item ? seriesLabel(item) : entry.seriesName
            return `${entry.marker}${label}: ${Number(entry.value).toFixed(2)}亿`
          })
        return `${axisLabel}<br/>${lines.join('<br/>')}`
      },
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
      name: props.mode === 'sector' ? s.id : s.name,
      type: 'line' as const,
      showSymbol: false,
      triggerLineEvent: true,
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

function buildPriceSeries(item: FlowSeries, tl: string[]) {
  if (!item.price_values) return null
  const aligned = alignValuesToTradingMinutes(tl, item.price_values)
  const tipIdx = lastNonNullIndex(aligned)
  if (tipIdx < 0) return null
  const data = aligned.map((value, index) => (index <= tipIdx ? value : null))
  const lastPrice = aligned[tipIdx]
  const priceColor = themeStore.isDark ? '#cbd5e1' : '#64748b'

  return {
    id: `${PRICE_SERIES_PREFIX}${item.id}`,
    name: `${PRICE_SERIES_PREFIX}${item.id}`,
    type: 'line' as const,
    yAxisIndex: 1,
    showSymbol: false,
    triggerLineEvent: false,
    connectNulls: false,
    smooth: 0.15,
    clip: false,
    data,
    z: 11,
    silent: true,
    lineStyle: {
      width: 1.8,
      type: 'dashed' as const,
      color: priceColor,
      opacity: 0.92,
      shadowBlur: 0,
      shadowColor: undefined,
    },
    itemStyle: { color: priceColor },
    endLabel: {
      show: true,
      formatter: () => `价 ${Number(lastPrice).toFixed(2)}`,
      color: priceColor,
      fontSize: 10,
      fontWeight: 600,
      distance: 6,
      backgroundColor: themeStore.isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.88)',
      padding: [2, 5, 2, 5],
      borderRadius: 4,
    },
    labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
  }
}

function resolveSeriesId(params: {
  seriesId?: string | number
  seriesName?: string
  seriesIndex?: number
}): string | null {
  const list = seriesList.value || []
  if (params.seriesId != null && params.seriesId !== '') {
    return String(params.seriesId)
  }
  if (params.seriesName) {
    const byId = list.find((s) => s.id === params.seriesName)
    if (byId) return byId.id
    const byName = list.find((s) => s.name === params.seriesName)
    if (byName) return byName.id
  }
  if (typeof params.seriesIndex === 'number' && list[params.seriesIndex]) {
    return list[params.seriesIndex]!.id
  }
  return null
}

function onChartClick(params: {
  componentType?: string
  seriesId?: string | number
  seriesName?: string
  seriesIndex?: number
}) {
  if (params.componentType !== 'series') return
  const id = resolveSeriesId(params)
  if (!id) return
  if (props.mode === 'sector') {
    void boardStore.selectSectorForLinkage(id)
  } else {
    boardStore.toggleHighlight(id, 'stock')
  }
}

function bindChartEvents() {
  if (!chart) return
  chart.off('click')
  chart.on('click', onChartClick)
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value)
    bindChartEvents()
  }

  if (showEmpty.value) {
    chart.clear()
    return
  }

  const tl = sourceTimeline.value || []
  const list = seriesList.value || []
  const { series, gridRight } = buildSeries(list, highlighted.value, tl)
  const chartSeries = [...series]
  if (showPriceOverlay.value && soloStockSeries.value) {
    const priceSeries = buildPriceSeries(soloStockSeries.value, tl)
    if (priceSeries) chartSeries.push(priceSeries)
  }

  chart.setOption(
    {
      backgroundColor: 'transparent',
      animation: false,
      ...baseAxis(gridRight, list, showPriceOverlay.value),
      series: chartSeries,
    },
    true,
  )
}

function resizeChart() {
  chart?.resize()
}

watch(
  [sourceTimeline, seriesList, highlighted, showEmpty, showPriceOverlay, () => props.mode, colors, () => themeStore.isDark],
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
