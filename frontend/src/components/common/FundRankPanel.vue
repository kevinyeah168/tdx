<script setup lang="ts">
import { NDataTable, NEmpty } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h } from 'vue'
import {
  DEFAULT_LINKAGE_TOP_K,
  MAX_CHART_SECTORS,
  chartVisibleCount,
} from '@/api/workbenchBoard'
import { useBoardStore } from '@/stores/boardStore'
import type { BoardItem, FlowSeries } from '@/types/board'
import { seriesColor } from '@/utils/chartColors'
import { valueAtTradingMinute } from '@/utils/tradingTimeline'
import {
  chgTone,
  fmtMoneyCompact,
  fmtNetRatio,
  fmtPct,
  sectorTypeShort,
  toneClass,
} from '@/utils/format'

function cleanLabel(value: string): string {
  return String(value || '').replace(/\u0000/g, '').trim()
}

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const { board, highlightedSector, highlightedStock, linkageSectorId, stockSourceMode, chartHoverMinute, chartHoverSource } =
  storeToRefs(boardStore)

const highlighted = computed(() => {
  if (props.mode === 'stock') return highlightedStock.value
  if (stockSourceMode.value === 'linkage' && linkageSectorId.value) {
    return linkageSectorId.value
  }
  return highlightedSector.value
})

const chartSolo = computed(() =>
  props.mode === 'stock' ? highlightedStock.value : highlightedSector.value,
)

const chartVisibleTotal = computed(() => chartVisibleCount(board.value.selected_boards ?? []))

const linkedHoverMinute = computed(() =>
  chartHoverSource.value === props.mode ? chartHoverMinute.value : null,
)

function stockValueAtHover(series: FlowSeries): FlowSeries {
  const minute = linkedHoverMinute.value
  const baseGray = series.cum_gray ?? null
  if (!minute) {
    return baseGray != null ? { ...series, cum_gray: baseGray } : series
  }
  const timeline = board.value.stock_timeline || []
  const main = valueAtTradingMinute(timeline, series.values || [], minute)
  const gray = series.gray_values?.length
    ? valueAtTradingMinute(timeline, series.gray_values, minute)
    : null
  const cumMain = main ?? series.cum_main
  const mainAmountRatio =
    series.daily_amount != null &&
    Number.isFinite(series.daily_amount) &&
    series.daily_amount > 0 &&
    cumMain != null &&
    Number.isFinite(cumMain)
      ? Math.round((cumMain / series.daily_amount) * 100 * 10000) / 10000
      : series.main_amount_ratio ?? null
  return {
    ...series,
    cum_main: cumMain,
    cum_gray: gray ?? baseGray,
    main_amount_ratio: mainAmountRatio,
  }
}

function sectorBoardAtHover(boardItem: BoardItem): BoardItem {
  const series = board.value.sector_series.find((item) => item.id === boardItem.id)
  const baseGray = boardItem.cum_gray ?? series?.cum_gray ?? null
  const minute = linkedHoverMinute.value
  if (!minute) {
    return baseGray != null ? { ...boardItem, cum_gray: baseGray } : boardItem
  }
  if (!series) return boardItem
  const timeline = board.value.timeline || []
  const main = valueAtTradingMinute(timeline, series.values || [], minute)
  const gray = series.gray_values?.length
    ? valueAtTradingMinute(timeline, series.gray_values, minute)
    : null
  return {
    ...boardItem,
    ...(main != null ? { cum_main: main } : {}),
    cum_gray: gray ?? baseGray,
  }
}

const importedIdSet = computed(
  () => new Set((board.value.imported_sector_boards ?? []).map((row) => row.id)),
)

const importedSectorRows = computed(() =>
  [...(board.value.imported_sector_boards ?? [])]
    .map((row) => sectorBoardAtHover(row))
    .sort((a, b) => Number(b.cum_main || 0) - Number(a.cum_main || 0)),
)

const groupSectorRows = computed(() =>
  [...(board.value.selected_boards ?? [])]
    .filter((row) => !importedIdSet.value.has(row.id))
    .map((row) => sectorBoardAtHover(row))
    .sort((a, b) => Number(b.cum_main || 0) - Number(a.cum_main || 0)),
)

const sectorRows = computed(() => groupSectorRows.value)

const stockRows = computed(() =>
  [...board.value.stock_series]
    .map((row) => stockValueAtHover(row))
    .sort((a, b) => Number(b.cum_main || 0) - Number(a.cum_main || 0)),
)

const rows = computed(() => (props.mode === 'stock' ? stockRows.value : sectorRows.value))

const groupPanelTitle = computed(
  () => board.value.active_sector_group_name || '板块分组',
)

const panelHint = computed(() => {
  const hoverSuffix = linkedHoverMinute.value ? ` · 光标 ${linkedHoverMinute.value}` : ''
  if (props.mode === 'stock') {
    if (!boardStore.linkageSectorId) {
      return `点击左侧板块联动前 ${DEFAULT_LINKAGE_TOP_K} 成分股`
    }
    const base = boardStore.linkageSectorName
      ? `联动 · ${boardStore.linkageSectorName}`
      : '联动成分股'
    return `${base}${hoverSuffix}`
  }
  const imported = board.value.imported_sector_boards?.length ?? 0
  const groupMembers = groupSectorRows.value.length
  const curves = board.value.sector_series?.length ?? 0
  return `曲线 ${curves}/${MAX_CHART_SECTORS} · 导入 ${imported} · 分组 ${groupMembers}${hoverSuffix}`
})

function sectorDotColor(row: BoardItem): string {
  const series = board.value.sector_series.find((item) => item.id === row.id)
  if (!series) return 'var(--muted)'
  return seriesColor(board.value.sector_series, series, 'sector')
}

function stockDotColor(row: FlowSeries): string {
  return seriesColor(board.value.stock_series, row, 'stock')
}

function rankHeader(label: string) {
  return () => h('span', { class: 'rank-th-label' }, label)
}

function renderRankMetric(
  value: number | null | undefined,
  opts?: { bold?: boolean; pct?: boolean; ratio?: boolean },
) {
  const text = opts?.pct ? fmtPct(value) : opts?.ratio ? fmtNetRatio(value) : fmtMoneyCompact(value)
  return h(
    'span',
    {
      class: [
        'rank-metric num whitespace-nowrap',
        opts?.bold ? 'font-600' : '',
        toneClass(chgTone(value)),
      ].join(' '),
    },
    text,
  )
}

const stockColumns = computed(() => [
  {
    title: rankHeader('个股'),
    key: 'name',
    width: 54,
    ellipsis: { tooltip: true },
    render(row: FlowSeries) {
      const name = cleanLabel(row.name)
      const code = cleanLabel(row.symbol || row.id)
      return h('div', { class: 'rank-row-name', title: `${name} ${code}` }, [
        h('span', {
          class: 'rank-row-dot shrink-0',
          style: { backgroundColor: stockDotColor(row) },
        }),
        h('span', { class: 'rank-name' }, name),
      ])
    },
  },
  {
    title: rankHeader('明盘'),
    key: 'cum_main',
    width: 58,
    align: 'right' as const,
    sorter: (a: FlowSeries, b: FlowSeries) =>
      Number(a.cum_main || 0) - Number(b.cum_main || 0),
    defaultSortOrder: 'descend' as const,
    render(row: FlowSeries) {
      return renderRankMetric(row.cum_main, { bold: true })
    },
  },
  {
    title: rankHeader('暗盘'),
    key: 'cum_gray',
    width: 58,
    align: 'right' as const,
    sorter: (a: FlowSeries, b: FlowSeries) =>
      Number(a.cum_gray || 0) - Number(b.cum_gray || 0),
    render(row: FlowSeries) {
      return renderRankMetric(row.cum_gray, { bold: true })
    },
  },
  {
    title: rankHeader('净比'),
    key: 'main_net_ratio',
    width: 40,
    align: 'right' as const,
    sorter: (a: FlowSeries, b: FlowSeries) => {
      const av = a.main_net_ratio
      const bv = b.main_net_ratio
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render(row: FlowSeries) {
      return renderRankMetric(row.main_net_ratio, { ratio: true })
    },
  },
  {
    title: rankHeader('占比'),
    key: 'main_amount_ratio',
    width: 40,
    align: 'right' as const,
    sorter: (a: FlowSeries, b: FlowSeries) => {
      const av = a.main_amount_ratio
      const bv = b.main_amount_ratio
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render(row: FlowSeries) {
      return renderRankMetric(row.main_amount_ratio, { ratio: true })
    },
  },
  {
    title: rankHeader('涨幅'),
    key: 'change_pct',
    width: 46,
    align: 'right' as const,
    sorter: (a: FlowSeries, b: FlowSeries) =>
      Number(a.change_pct || 0) - Number(b.change_pct || 0),
    render(row: FlowSeries) {
      return renderRankMetric(row.change_pct, { pct: true })
    },
  },
])

const sectorColumns = computed(() => [
  {
    title: rankHeader('板块'),
    key: 'name',
    width: 62,
    ellipsis: { tooltip: true },
    render(row: BoardItem) {
      const typeLabel = sectorTypeShort(row.sector_type, row.id)
      return h(
        'div',
        { class: 'rank-row-name', title: `${row.name} ${row.id} · ${typeLabel}` },
        [
          h('span', {
            class: 'rank-row-dot shrink-0',
            style: { backgroundColor: sectorDotColor(row) },
          }),
          h('span', { class: 'rank-name' }, cleanLabel(row.name)),
        ],
      )
    },
  },
  {
    title: rankHeader('明盘'),
    key: 'cum_main',
    width: 64,
    align: 'right' as const,
    className: 'rank-col-main',
    sorter: (a: BoardItem, b: BoardItem) => Number(a.cum_main || 0) - Number(b.cum_main || 0),
    defaultSortOrder: 'descend' as const,
    render(row: BoardItem) {
      return renderRankMetric(row.cum_main, { bold: true })
    },
  },
  {
    title: rankHeader('暗盘'),
    key: 'cum_gray',
    width: 46,
    align: 'right' as const,
    className: 'rank-col-gray',
    sorter: (a: BoardItem, b: BoardItem) =>
      Number(a.cum_gray || 0) - Number(b.cum_gray || 0),
    render(row: BoardItem) {
      return renderRankMetric(row.cum_gray, { bold: true })
    },
  },
  {
    title: rankHeader('涨幅'),
    key: 'change_pct',
    width: 48,
    align: 'right' as const,
    className: 'rank-col-change',
    sorter: (a: BoardItem, b: BoardItem) =>
      Number(a.change_pct || 0) - Number(b.change_pct || 0),
    render(row: BoardItem) {
      return renderRankMetric(row.change_pct, { pct: true })
    },
  },
])

const columns = computed(() => (props.mode === 'stock' ? stockColumns.value : sectorColumns.value))

function rowProps(row: BoardItem | FlowSeries) {
  const id = row.id
  const isActive =
    props.mode === 'sector'
      ? chartSolo.value === id || highlighted.value === id
      : highlighted.value === id
  const dimmed =
    props.mode === 'sector' && 'chart_visible' in row && row.chart_visible === false
  return {
    class: [isActive ? 'active-row' : '', dimmed ? 'dim-row' : ''].filter(Boolean).join(' '),
    style: { cursor: 'pointer' },
    onClick: () => {
      if (props.mode === 'sector') {
        void boardStore.selectSectorForLinkage(id)
      } else {
        boardStore.toggleHighlight(id, props.mode)
      }
    },
  }
}
</script>

<template>
  <aside class="panel-card rank-aside flex min-h-0 flex-1 flex-col overflow-hidden p-2">
    <div class="mb-1 flex items-center justify-between gap-2 border-b border-[var(--border)] px-0.5 pb-1.5">
      <span class="shrink-0 text-xs font-600">{{ mode === 'stock' ? '榜单' : '板块信息' }}</span>
      <span class="truncate text-right text-[10px] text-[var(--muted)]">{{ panelHint }}</span>
    </div>

    <template v-if="mode === 'sector'">
      <div class="rank-sections min-h-0 flex flex-1 flex-col overflow-hidden">
      <div v-if="importedSectorRows.length" class="rank-section rank-section--imported">
        <div class="rank-section-head">
          <span class="rank-section-title">导入板块</span>
          <span class="rank-section-count">({{ importedSectorRows.length }})</span>
        </div>
        <NDataTable
          :columns="columns"
          :data="importedSectorRows"
          :bordered="false"
          size="small"
          :single-line="true"
          class="rank-table rank-table--sector rank-table-section"
          :row-props="rowProps"
        />
      </div>

      <div class="rank-section rank-section--group min-h-0 flex-1">
        <div class="rank-section-head">
          <span class="rank-section-title">{{ groupPanelTitle }}</span>
          <span class="rank-section-count">({{ groupSectorRows.length }})</span>
        </div>
        <NDataTable
          v-if="groupSectorRows.length"
          :columns="columns"
          :data="groupSectorRows"
          :bordered="false"
          size="small"
          :single-line="true"
          flex-height
          class="rank-table rank-table--sector rank-table-section min-h-0 flex-1"
          :row-props="rowProps"
        />
        <NEmpty
          v-else
          class="rank-empty py-6"
          :description="
            board.active_sector_group_id
              ? '当前分组为空，请在「管理分组」添加板块'
              : '请先创建板块分组'
          "
          size="small"
        />
      </div>
      </div>
    </template>

    <template v-else>
      <NDataTable
        v-if="rows.length"
        :columns="columns"
        :data="rows"
        :bordered="false"
        size="small"
        :single-line="true"
        flex-height
        class="rank-table rank-table--stock min-h-0 flex-1"
        :row-props="rowProps"
      />
      <NEmpty
        v-else
        class="py-8"
        :description="
          !boardStore.linkageSectorId
            ? `点击左侧板块查看前 ${DEFAULT_LINKAGE_TOP_K} 成分股`
            : '暂无个股曲线'
        "
        size="small"
      />
    </template>
  </aside>
</template>

<style scoped>
.rank-aside {
  min-width: 0;
}

.rank-section {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 4px;
}

.rank-sections {
  gap: 4px;
}

.rank-section--imported {
  flex: 0 0 auto;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}

.rank-section--group {
  flex: 1;
}

.rank-section-head {
  display: flex;
  align-items: baseline;
  gap: 4px;
  padding: 0 2px;
}

.rank-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
}

.rank-section-count {
  font-size: 10px;
  color: var(--muted);
}

.rank-table-section :deep(.n-data-table-wrapper) {
  min-height: 0;
}

:deep(.rank-table .n-data-table-table) {
  table-layout: fixed;
  width: 100%;
}

:deep(.rank-table .n-data-table-th),
:deep(.rank-table .n-data-table-td) {
  padding: 4px 2px !important;
  font-size: 10px;
  white-space: nowrap;
}

:deep(.rank-table .n-data-table-th) {
  font-size: 10px;
  font-weight: 600;
}

:deep(.rank-table .n-data-table-th__title-wrapper),
:deep(.rank-table .n-data-table-th__title),
:deep(.rank-table .n-data-table-sorter) {
  white-space: nowrap !important;
  flex-wrap: nowrap !important;
}

:deep(.rank-th-label) {
  white-space: nowrap;
  line-height: 1;
}

:deep(.rank-table .n-data-table-th:last-child),
:deep(.rank-table .n-data-table-td:last-child) {
  padding-right: 6px !important;
}

:deep(.rank-table--sector .rank-col-main) {
  padding-right: 14px !important;
}

:deep(.rank-table--sector .rank-col-gray) {
  padding-left: 10px !important;
  padding-right: 16px !important;
}

:deep(.rank-table--sector .rank-col-change) {
  padding-left: 10px !important;
}

:deep(.rank-row-name) {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 3px;
}

:deep(.dim-row) {
  opacity: 0.45;
}

:deep(.rank-row-dot) {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 9999px;
}

:deep(.rank-name) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.2;
}

:deep(.rank-metric) {
  display: inline-block;
  width: 100%;
  text-align: right;
  font-size: 10px;
  line-height: 1.2;
}

:deep(.rank-metric.text-up) {
  color: var(--up);
}

:deep(.rank-metric.text-down) {
  color: var(--down);
}

:deep(.rank-metric.text-flat) {
  color: var(--muted);
}
</style>
