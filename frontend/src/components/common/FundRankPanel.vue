<script setup lang="ts">
import { NDataTable, NEmpty } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import type { FlowSeries } from '@/types/board'
import { seriesColor } from '@/utils/chartColors'
import { chgTone, fmtMoney, fmtPct, toneClass } from '@/utils/format'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const { board, highlightedSector, highlightedStock } = storeToRefs(boardStore)

const highlighted = computed(() =>
  props.mode === 'stock' ? highlightedStock.value : highlightedSector.value,
)

const rows = computed(() =>
  props.mode === 'stock' ? boardStore.sortedStocks() : boardStore.sortedSectors(),
)

const panelHint = computed(() =>
  props.mode === 'stock'
    ? `${boardStore.stockModeLabel} · 点击高亮`
    : `${boardStore.sectorModeLabel} · 点击高亮`,
)

const nameColumnTitle = computed(() =>
  props.mode === 'stock' ? '个股' : '板块',
)

const columns = computed(() => [
  {
    title: '',
    key: 'dot',
    width: 22,
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
    ellipsis: { tooltip: true },
    render(row: FlowSeries) {
      if (props.mode === 'stock') {
        const code = row.symbol || row.id
        return h('div', { class: 'min-w-0' }, [
          h('div', { class: 'truncate text-xs font-500' }, row.name),
          h('div', { class: 'num text-[10px] text-[var(--muted)]' }, code),
        ])
      }
      return h('div', { class: 'min-w-0' }, [
        h('div', { class: 'truncate text-xs font-500' }, row.name),
        h('div', { class: 'num text-[10px] text-[var(--muted)]' }, row.id),
      ])
    },
  },
  {
    title: '主力',
    key: 'cum_main',
    width: 80,
    sorter: (a: FlowSeries, b: FlowSeries) =>
      Number(a.cum_main || 0) - Number(b.cum_main || 0),
    defaultSortOrder: 'descend' as const,
    render(row: FlowSeries) {
      return h(
        'span',
        { class: `num text-[11px] font-600 ${toneClass(chgTone(row.cum_main))}` },
        fmtMoney(row.cum_main),
      )
    },
  },
  {
    title: '涨跌',
    key: 'change_pct',
    width: 58,
    render(row: FlowSeries) {
      return h(
        'span',
        { class: `num text-[11px] ${toneClass(chgTone(row.change_pct))}` },
        fmtPct(row.change_pct),
      )
    },
  },
])

function rowProps(row: FlowSeries) {
  return {
    class: highlighted.value === row.id ? 'active-row' : '',
    style: { cursor: 'pointer' },
    onClick: () => boardStore.toggleHighlight(row.id, props.mode),
  }
}
</script>

<template>
  <aside class="panel-card flex min-h-0 flex-1 flex-col overflow-hidden p-2">
    <div class="mb-1 flex items-center justify-between border-b border-[var(--border)] px-0.5 pb-1.5">
      <span class="text-xs font-600">榜单</span>
      <span class="text-[10px] text-[var(--muted)]">{{ panelHint }}</span>
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
      :description="mode === 'stock' ? '暂无个股曲线' : '暂无板块曲线'"
      size="small"
    />
  </aside>
</template>

<style scoped>
:deep(.n-data-table-th) {
  font-size: 11px;
  font-weight: 600;
}
</style>
