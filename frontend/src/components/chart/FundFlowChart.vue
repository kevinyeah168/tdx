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
import { isWeekdayDate } from '@/utils/tradingSession'
import { todayTradeDate } from '@/utils/tradeDate'
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

const soloSeries = computed(() => {
  if (!highlighted.value) return null
  return seriesList.value.find((item) => item.id === highlighted.value) ?? null
})

const showPriceOverlay = computed(() => {
  const solo = soloSeries.value
  if (!solo) return false
  const hasPrice = Boolean(solo.price_values?.some((value) => value != null))
  const hasAvg = Boolean(solo.avg_price_values?.some((value) => value != null))
  return hasPrice || hasAvg
})

const showGrayOverlay = computed(() => {
  if (props.mode !== 'stock') return false
  const solo = soloSeries.value
  if (!solo) return false
  return Boolean(solo.gray_values?.some((value) => value != null))
})

const PRICE_SERIES_PREFIX = '__price__:'
const AVG_PRICE_SERIES_PREFIX = '__avg_price__:'
const GRAY_SERIES_PREFIX = '__gray__:'

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
  const calendarToday = todayTradeDate()
  const viewingToday = vd === calendarToday
  if (viewingToday && session?.marketStatus === 'pre_open') return true
  if (!seriesList.value.length) return true
  return !hasChartData.value
})

const emptyTitle = computed(() => {
  const session = board.value.trading_session
  const vd = viewDate.value
  if (vd && !isWeekdayDate(vd)) return '非交易日'
  if (session?.marketStatus === 'pre_open' && vd === todayTradeDate()) return '尚未开盘'
  if (session?.marketStatus === 'open' && vd === todayTradeDate()) return '加载中'
  return '暂无分时数据'
})

const emptyMessage = computed(() => {
  const session = board.value.trading_session
  if (session?.message) return session.message
  const vd = viewDate.value
  const calendarToday = todayTradeDate()
  if (vd && vd !== calendarToday) return '该交易日暂无采样数据'
  return '今日尚未开盘，数据在交易日 09:31 开始实时更新'
})

function seriesLabel(item: FlowSeries): string {
  if (props.mode === 'sector') return fmtSectorSeriesLabel(item)
  return cleanLabel(item.name)
}

function cleanLabel(value: string): string {
  return value.replace(/\u0000/g, '').trim()
}

function shortLabel(item: FlowSeries, max = 10): string {
  const label = seriesLabel(item)
  return label.length > max ? `${label.slice(0, max)}…` : label
}

function endLabelStyle(
  color: string,
  emphasized: boolean,
  list: FlowSeries[],
  lastYi?: number | null,
) {
  return {
    show: true,
    formatter: (params: { seriesName?: string; value?: number | null }) => {
      const item = list.find(
        (s) => s.id === params.seriesName || s.name === params.seriesName,
      )
      const label = emphasized ? '明盘' : item ? shortLabel(item) : cleanLabel(params.seriesName || '')
      const yi =
        lastYi != null && Number.isFinite(lastYi)
          ? lastYi
          : params.value != null && Number.isFinite(Number(params.value))
            ? Number(params.value)
            : null
      const money =
        yi != null ? fmtMoney(yi * 1e8) : item ? fmtMoney(item.cum_main) : '—'
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

/** Solo + 价格叠加时，资金轴必须按「亿」独立定标，否则会被指数/股价（千级）压成平线。 */
function fundAxisExtent(
  list: FlowSeries[],
  hl: string | null,
  tl: string[],
  solo: FlowSeries | null = null,
): { min: number; max: number } | null {
  const items = hl ? list.filter((item) => item.id === hl) : list
  const nums: number[] = []
  for (const item of items) {
    const aligned = alignValuesToTradingMinutes(tl, item.values || [])
    for (const value of aligned) {
      if (value != null && Number.isFinite(value)) nums.push(toYi(value))
    }
  }
  if (solo?.gray_values?.length) {
    const alignedGray = alignValuesToTradingMinutes(tl, solo.gray_values)
    for (const value of alignedGray) {
      if (value != null && Number.isFinite(value)) nums.push(toYi(value))
    }
  }
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

function baseAxis(
  gridRight: number,
  list: FlowSeries[],
  showPrice = false,
  priceMode: 'stock' | 'sector' = 'stock',
  fundExtent: { min: number; max: number } | null = null,
) {
  const c = colors.value
  const seriesCount = seriesList.value.length
  const tipMaxH = chartTipMaxHeight()
  const dense = seriesCount > 10
  const fundAxis: Record<string, unknown> = {
    id: 'fund',
    scale: !fundExtent,
    axisLabel: {
      color: c.axis,
      formatter: (v: number) => Number(v).toFixed(Math.abs(v) >= 100 ? 0 : 1),
      fontSize: 10,
    },
    name: '亿',
    nameTextStyle: { color: c.axis, fontSize: 10 },
    splitLine: { lineStyle: { color: c.splitLine } },
  }
  if (fundExtent) {
    fundAxis.min = fundExtent.min
    fundAxis.max = fundExtent.max
  }
  const yAxis: object[] = [fundAxis]
  if (showPrice) {
    yAxis.push({
      id: 'price',
      scale: true,
      position: 'right',
      alignTicks: false,
      axisLabel: { color: c.axis, formatter: (v: number) => v.toFixed(2), fontSize: 10 },
      name: priceMode === 'sector' ? '指数' : '价格',
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
            if (seriesKey.startsWith(AVG_PRICE_SERIES_PREFIX)) {
              return `${entry.marker}均价: ${Number(entry.value).toFixed(2)}`
            }
            if (seriesKey.startsWith(PRICE_SERIES_PREFIX)) {
              const solo = soloSeries.value
              const pct = solo?.change_pct
              const pctText = pct != null ? ` (${fmtPct(pct)})` : ''
              const label = props.mode === 'sector' ? '指数' : '股价'
              return `${entry.marker}${label}: ${Number(entry.value).toFixed(2)}${pctText}`
            }
            if (seriesKey.startsWith(GRAY_SERIES_PREFIX)) {
              return `${entry.marker}暗盘: ${Number(entry.value).toFixed(2)}亿`
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

function applySnapshotTip(
  valuesYi: (number | null)[],
  cumMain: number | null | undefined,
  sessionTimeline: string[],
): { values: (number | null)[]; tipIdx: number; lastYi: number | null } {
  const tipIdx = lastNonNullIndex(valuesYi)
  if (cumMain == null || !Number.isFinite(cumMain)) {
    return {
      values: valuesYi,
      tipIdx,
      lastYi: tipIdx >= 0 ? valuesYi[tipIdx] : null,
    }
  }
  const snapYi = toYi(cumMain)
  const sessionEnd = sessionTimeline[sessionTimeline.length - 1]
  const endIdx = sessionEnd ? TRADING_MINUTES.indexOf(sessionEnd) : -1
  if (endIdx < 0) {
    return { values: valuesYi, tipIdx, lastYi: snapYi }
  }
  const out = [...valuesYi]
  const startIdx = tipIdx >= 0 ? tipIdx : 0
  const tipVal = tipIdx >= 0 ? out[tipIdx] : null
  const staleTip =
    tipVal == null || !Number.isFinite(tipVal) || Math.abs(snapYi - Number(tipVal)) > 0.5
  if (staleTip) {
    for (let i = startIdx; i <= endIdx; i++) out[i] = snapYi
  } else {
    for (let i = startIdx + 1; i <= endIdx; i++) out[i] = snapYi
  }
  const nextTipIdx = lastNonNullIndex(out)
  return {
    values: out,
    tipIdx: nextTipIdx,
    lastYi: snapYi,
  }
}

function buildSeries(list: FlowSeries[], hl: string | null, tl: string[], soloOnly = false) {
  // Solo + 价格叠加时只画选中序列，避免其它曲线（或错误量纲）污染左轴「亿」尺度。
  const renderList = soloOnly && hl ? list.filter((s) => s.id === hl) : list
  const visible = renderList.filter((s) => !hl || hl === s.id)
  const gridRight = Math.max(148, Math.min(240, 96 + visible.length * 14))

  const series = renderList.map((s) => {
    const active = !hl || hl === s.id
    const color = seriesColor(list, s, props.mode)
    const aligned = alignValuesToTradingMinutes(tl, s.values || [])
    const baseYi = aligned.map((v) => (v == null ? null : toYi(v)))
    const { values: valuesYi, tipIdx, lastYi } = applySnapshotTip(baseYi, s.cum_main, tl)
    // Truncate trailing nulls so ECharts endLabel sits on the last captured point
    const data = tipIdx >= 0 ? valuesYi.slice(0, tipIdx + 1) : []

    return {
      id: s.id,
      name: props.mode === 'sector' ? s.id : s.name,
      type: 'line' as const,
      yAxisIndex: 0,
      showSymbol: false,
      triggerLineEvent: true,
      connectNulls: false,
      smooth: 0.15,
      clip: true,
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
          ? endLabelStyle(color, hl === s.id, list, lastYi)
          : { show: false },
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
    }
  })

  return { series, gridRight }
}

function buildOverlayPriceSeries(
  item: FlowSeries,
  tl: string[],
  kind: 'avg' | 'close',
): echarts.SeriesOption | null {
  const source = kind === 'avg' ? item.avg_price_values : item.price_values
  if (!source) return null
  const aligned = alignValuesToTradingMinutes(tl, source)
  const tipIdx = lastNonNullIndex(aligned)
  if (tipIdx < 0) return null
  const data = aligned.map((value, index) => (index <= tipIdx ? value : null))
  const lastValue = aligned[tipIdx]
  const isStock = props.mode === 'stock'
  const label = kind === 'avg' ? '均价' : isStock ? '股价' : '指数'
  const color =
    kind === 'avg'
      ? themeStore.isDark
        ? '#60a5fa'
        : '#2563eb'
      : themeStore.isDark
        ? '#94a3b8'
        : '#64748b'
  const prefix = kind === 'avg' ? AVG_PRICE_SERIES_PREFIX : PRICE_SERIES_PREFIX

  return {
    id: `${prefix}${item.id}`,
    name: `${prefix}${item.id}`,
    type: 'line' as const,
    yAxisIndex: 1,
    xAxisIndex: 0,
    showSymbol: false,
    triggerLineEvent: false,
    connectNulls: false,
    smooth: 0.15,
    clip: true,
    data,
    z: kind === 'avg' ? 12 : 11,
    silent: true,
    lineStyle: {
      width: kind === 'avg' ? 2 : 1.8,
      type: kind === 'avg' ? ('solid' as const) : ('dashed' as const),
      color,
      opacity: 0.95,
    },
    itemStyle: { color },
    endLabel: {
      show: true,
      formatter: () => `${label} ${Number(lastValue).toFixed(2)}`,
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
}

function buildPriceOverlaySeries(item: FlowSeries, tl: string[]): echarts.SeriesOption[] {
  const overlays: echarts.SeriesOption[] = []
  if (props.mode === 'stock') {
    const avgSeries = buildOverlayPriceSeries(item, tl, 'avg')
    const closeSeries = buildOverlayPriceSeries(item, tl, 'close')
    if (avgSeries) overlays.push(avgSeries)
    if (closeSeries) overlays.push(closeSeries)
  } else {
    const indexSeries = buildOverlayPriceSeries(item, tl, 'close')
    if (indexSeries) overlays.push(indexSeries)
  }
  return overlays
}

function buildGrayOverlaySeries(item: FlowSeries, tl: string[]): echarts.SeriesOption | null {
  if (!item.gray_values?.length) return null
  const aligned = alignValuesToTradingMinutes(tl, item.gray_values)
  const valuesYi = aligned.map((value) => (value == null ? null : toYi(value)))
  const tipIdx = lastNonNullIndex(valuesYi)
  if (tipIdx < 0) return null
  const data = valuesYi.slice(0, tipIdx + 1)
  const lastYi = valuesYi[tipIdx]
  const color = themeStore.isDark ? '#c084fc' : '#9333ea'

  return {
    id: `${GRAY_SERIES_PREFIX}${item.id}`,
    name: `${GRAY_SERIES_PREFIX}${item.id}`,
    type: 'line' as const,
    yAxisIndex: 0,
    xAxisIndex: 0,
    showSymbol: false,
    triggerLineEvent: false,
    connectNulls: false,
    smooth: 0.15,
    clip: true,
    data,
    z: 9,
    silent: true,
    lineStyle: {
      width: 2,
      type: 'solid' as const,
      color,
      opacity: 0.95,
    },
    itemStyle: { color },
    endLabel: {
      show: true,
      formatter: () =>
        lastYi != null && Number.isFinite(lastYi) ? `暗盘 ${fmtMoney(lastYi * 1e8)}` : '暗盘',
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
  const showPrice = showPriceOverlay.value
  const showGray = showGrayOverlay.value
  const soloOverlay = showPrice || showGray
  const hl = highlighted.value
  const { series, gridRight } = buildSeries(list, hl, tl, soloOverlay)
  const chartSeries = [...series] as echarts.SeriesOption[]
  if (showPrice && soloSeries.value) {
    chartSeries.push(...buildPriceOverlaySeries(soloSeries.value, tl))
  }
  if (showGray && soloSeries.value) {
    const graySeries = buildGrayOverlaySeries(soloSeries.value, tl)
    if (graySeries) chartSeries.push(graySeries)
  }
  const fundExtent = soloOverlay ? fundAxisExtent(list, hl, tl, soloSeries.value) : null

  chart.setOption(
    {
      backgroundColor: 'transparent',
      animation: false,
      ...baseAxis(gridRight, list, showPrice, props.mode, fundExtent),
      series: chartSeries,
    },
    true,
  )
}

function resizeChart() {
  chart?.resize()
}

watch(
  [sourceTimeline, seriesList, highlighted, showEmpty, showPriceOverlay, showGrayOverlay, () => props.mode, colors, () => themeStore.isDark],
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
