<script setup lang="ts">
import { NDataTable, NEmpty } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h } from 'vue'
import { MAX_CHART_SECTORS, chartVisibleCount } from '@/api/workbenchBoard'
import { useBoardStore } from '@/stores/boardStore'
import type { BoardItem, FlowSeries } from '@/types/board'
import { seriesColor } from '@/utils/chartColors'
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
const { board, highlightedSector, highlightedStock, linkageSectorId, stockSourceMode } =
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

const sectorRows = computed(() =>
  [...(board.value.selected_boards ?? [])]
    .filter((board) => board.chart_visible)
    .sort((a, b) => Number(b.cum_main || 0) - Number(a.cum_main || 0)),
)

const stockRows = computed(() => [...board.value.stock_series])

const rows = computed(() => (props.mode === 'stock' ? stockRows.value : sectorRows.value))

const panelTitle = computed(() => (props.mode === 'stock' ? '榜单' : '自选板块'))

const panelHint = computed(() => {
  if (props.mode === 'stock') {
    if (!boardStore.linkageSectorId) {
      return '点击左侧板块联动前 20 成分股'
    }
    return boardStore.linkageSectorName ? `联动 · ${boardStore.linkageSectorName}` : '联动成分股'
  }
  const selected = board.value.selected_boards?.length ?? 0
  return `图表 ${chartVisibleTotal.value}/${MAX_CHART_SECTORS} · 自选 ${selected}`
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
    width: 68,
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
    width: 62,
    align: 'right' as const,
    sorter: (a: BoardItem, b: BoardItem) => Number(a.cum_main || 0) - Number(b.cum_main || 0),
    defaultSortOrder: 'descend' as const,
    render(row: BoardItem) {
      return renderRankMetric(row.cum_main, { bold: true })
    },
  },
  {
    title: rankHeader('涨幅'),
    key: 'change_pct',
    width: 46,
    align: 'right' as const,
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
  return {
    class: isActive ? 'active-row' : '',
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
      <span class="shrink-0 text-xs font-600">{{ panelTitle }}</span>
      <span class="truncate text-right text-[10px] text-[var(--muted)]">{{ panelHint }}</span>
    </div>

    <NDataTable
      v-if="rows.length"
      :columns="columns"
      :data="rows"
      :bordered="false"
      size="small"
      :single-line="true"
      flex-height
      :class="['rank-table min-h-0 flex-1', mode === 'stock' ? 'rank-table--stock' : 'rank-table--sector']"
      :row-props="rowProps"
    />
    <NEmpty
      v-else
      class="py-8"
      :description="
        mode === 'stock' && !boardStore.linkageSectorId
          ? '点击左侧板块查看前 20 成分股'
            : mode === 'stock'
            ? '暂无个股曲线'
            : chartVisibleTotal
              ? '暂无展示板块，请在「管理自选」勾选展示曲线'
              : '尚未添加自选板块，请点击「管理自选」添加'
      "
      size="small"
    />
  </aside>
</template>

<style scoped>
.rank-aside {
  min-width: 0;
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

:deep(.rank-row-name) {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 3px;
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
</style>
