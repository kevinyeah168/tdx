<script setup lang="ts">
import { NDataTable, NEmpty } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import type { FlowSeries } from '@/types/board'
import { seriesColor } from '@/utils/chartColors'
import { chgTone, fmtMoneyCompact, fmtPct, sectorTypeShort, toneClass } from '@/utils/format'
import { sectorTypeClass } from '@/utils/sectorTypeStyles'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const { board, highlightedSector, highlightedStock, linkageSectorId, stockSourceMode } =
  storeToRefs(boardStore)

/** 列表选中态：联动模式下跟联动板块；图表solo高亮仍用 highlighted* */
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

const rows = computed(() =>
  props.mode === 'stock' ? boardStore.sortedStocks() : boardStore.sortedSectors(),
)

const panelHint = computed(() => {
  if (props.mode === 'stock') {
    if (boardStore.stockSourceMode === 'linkage' && !boardStore.linkageSectorId) {
      return '点击左侧板块联动'
    }
    return `${boardStore.stockModeLabel} · 点击高亮`
  }
  if (boardStore.stockSourceMode === 'linkage') {
    return `${boardStore.sectorModeLabel} · 点击联动，再点复原`
  }
  return `${boardStore.sectorModeLabel} · 点击高亮`
})

const nameColumnTitle = computed(() =>
  props.mode === 'stock' ? '个股' : '板块',
)

const columns = computed(() => [
  {
    title: '',
    key: 'dot',
    width: 16,
    render(row: FlowSeries) {
      const list =
        props.mode === 'stock' ? board.value.stock_series : board.value.sector_series
      const color = seriesColor(list, row, props.mode)
      return h('span', {
        class: 'inline-block h-2 w-2 rounded-full',
        style: { backgroundColor: color },
      })
    },
  },
  {
    title: nameColumnTitle.value,
    key: 'name',
    minWidth: 108,
    ellipsis: { tooltip: true },
    render(row: FlowSeries) {
      if (props.mode === 'stock') {
        const code = row.symbol || row.id
        return h('div', { class: 'rank-name-cell' }, [
          h('div', { class: 'rank-name text-xs font-500', title: row.name }, row.name),
          h('div', { class: 'num text-[10px] text-[var(--muted)]' }, code),
        ])
      }
      return h('div', { class: 'rank-name-cell' }, [
        h('div', { class: 'rank-name text-xs font-500', title: row.name }, row.name),
        h('div', { class: 'rank-meta flex min-w-0 items-center gap-1' }, [
          h('span', { class: 'num shrink-0 text-[10px] text-[var(--muted)]' }, row.id),
          h(
            'span',
            {
              class: ['sector-type-badge rank-type-badge', sectorTypeClass(row.sector_type, row.id)],
            },
            sectorTypeShort(row.sector_type, row.id),
          ),
        ]),
      ])
    },
  },
  {
    title: '主力',
    key: 'cum_main',
    width: 68,
    align: 'right' as const,
    sorter: (a: FlowSeries, b: FlowSeries) =>
      Number(a.cum_main || 0) - Number(b.cum_main || 0),
    defaultSortOrder: 'descend' as const,
    render(row: FlowSeries) {
      return h(
        'span',
        { class: `num text-[11px] font-600 whitespace-nowrap ${toneClass(chgTone(row.cum_main))}` },
        fmtMoneyCompact(row.cum_main),
      )
    },
  },
  {
    title: '涨跌',
    key: 'change_pct',
    width: 56,
    align: 'right' as const,
    render(row: FlowSeries) {
      return h(
        'span',
        {
          class: `rank-pct num text-[11px] ${toneClass(chgTone(row.change_pct))}`,
        },
        fmtPct(row.change_pct),
      )
    },
  },
])

function rowProps(row: FlowSeries) {
  const isActive =
    props.mode === 'sector'
      ? chartSolo.value === row.id || highlighted.value === row.id
      : highlighted.value === row.id
  return {
    class: isActive ? 'active-row' : '',
    style: { cursor: 'pointer' },
    onClick: () => {
      if (props.mode === 'sector') {
        void boardStore.selectSectorForLinkage(row.id)
      } else {
        boardStore.toggleHighlight(row.id, props.mode)
      }
    },
  }
}
</script>

<template>
  <aside class="panel-card flex min-h-0 flex-1 flex-col overflow-hidden p-2">
    <div class="mb-1 flex items-center justify-between gap-2 border-b border-[var(--border)] px-0.5 pb-1.5">
      <span class="shrink-0 text-xs font-600">榜单</span>
      <span class="truncate text-right text-[10px] text-[var(--muted)]">{{ panelHint }}</span>
    </div>

    <NDataTable
      v-if="rows.length"
      :columns="columns"
      :data="rows"
      :bordered="false"
      size="small"
      :single-line="false"
      flex-height
      class="min-h-0 flex-1"
      :row-props="rowProps"
    />
    <NEmpty
      v-else
      class="py-8"
      :description="
        mode === 'stock' && boardStore.stockSourceMode === 'linkage' && !boardStore.linkageSectorId
          ? '点击左侧板块查看成分股主力'
          : mode === 'stock' && boardStore.stockSourceMode === 'selected'
            ? '尚未添加自选个股'
            : mode === 'sector' && boardStore.sectorSourceMode === 'selected'
              ? '尚未添加自选板块'
              : mode === 'stock'
                ? '暂无个股曲线'
                : '暂无板块曲线'
      "
      size="small"
    />
  </aside>
</template>

<style scoped>
:deep(.n-data-table-th) {
  font-size: 11px;
  font-weight: 600;
  padding-left: 4px !important;
  padding-right: 4px !important;
}

:deep(.n-data-table-td) {
  padding-left: 4px !important;
  padding-right: 4px !important;
}

:deep(.rank-name-cell) {
  min-width: 0;
}

:deep(.rank-name) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.35;
}

:deep(.rank-type-badge) {
  padding: 0 4px;
  font-size: 9px;
}

:deep(.rank-pct) {
  display: inline-block;
  white-space: nowrap;
}

:deep(.n-data-table-td:last-child),
:deep(.n-data-table-th:last-child) {
  white-space: nowrap;
}
</style>
