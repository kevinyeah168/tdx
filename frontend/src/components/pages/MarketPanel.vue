<script setup lang="ts">
import FundFlowChart from '@/components/chart/FundFlowChart.vue'
import FundRankPanel from '@/components/common/FundRankPanel.vue'
import IntradayDatePicker from '@/components/common/IntradayDatePicker.vue'
import MarketScopePanel from '@/components/workbench/MarketScopePanel.vue'
import { NButton, NSelect, NSpin } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useBoardStore } from '@/stores/boardStore'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const {
  board,
  sectorLoading,
  sectorLoadingHint,
  stockLoading,
  stockLoadingHint,
  linkageSectorName,
  highlightedStock,
  highlightedSector,
  sectorGroups,
  activeSectorGroupId,
  stockSourceMode,
  sectorViewDate,
} = storeToRefs(boardStore)

const showDatePicker = computed(
  () => props.mode === 'sector' || stockSourceMode.value !== 'linkage',
)

const highlightedStockSeries = computed(() => {
  const id = highlightedStock.value
  if (!id) return null
  return board.value.stock_series?.find((item) => item.id === id) ?? null
})

const title = computed(() => {
  if (props.mode === 'stock') {
    return linkageSectorName.value ? `个股主力 · ${linkageSectorName.value}` : '个股主力'
  }
  return '板块资金走势'
})

const soloStockLabel = computed(() => highlightedStockSeries.value?.name ?? null)

const soloSectorLabel = computed(() => {
  if (!highlightedSector.value) return null
  return (
    board.value.sector_series.find((item) => item.id === highlightedSector.value)?.name ??
    board.value.selected_boards.find((item) => item.id === highlightedSector.value)?.name ??
    null
  )
})

const count = computed(() => {
  if (props.mode === 'stock') {
    if (stockSourceMode.value === 'linkage') {
      const watchlistCount = board.value.watchlist?.length ?? 0
      if (watchlistCount > 0) return watchlistCount
    }
    return board.value.stock_series?.length ?? 0
  }
  return board.value.sector_series?.length ?? 0
})

const groupMemberTotal = computed(() => board.value.selected_boards?.length ?? 0)

const countLabel = computed(() => {
  if (props.mode === 'stock') return `(${count.value})`
  if (groupMemberTotal.value > count.value) {
    return `(${count.value}/${groupMemberTotal.value})`
  }
  return `(${count.value})`
})

const groupSelectOptions = computed(() =>
  sectorGroups.value.map((group) => ({
    label: `${group.name} (${group.sector_ids.length})`,
    value: group.id,
  })),
)

function switchGroup(groupId: string | null) {
  if (!groupId) return
  void boardStore.switchSectorGroup(groupId)
}

const showLoading = computed(() =>
  props.mode === 'stock' ? stockLoading.value : sectorLoading.value,
)

const loadingHint = computed(() => {
  if (props.mode === 'stock') return stockLoadingHint.value || '加载个股主力…'
  return sectorLoadingHint.value || '加载板块数据…'
})
</script>

<template>
  <section class="flex h-full min-h-0 flex-col gap-2">
    <div class="flex shrink-0 items-center justify-between gap-2 px-1">
      <div class="flex min-w-0 items-center gap-2">
        <h2 class="m-0 flex min-w-0 items-center gap-1.5 text-sm font-600 text-[var(--text)]">
          <span class="truncate">{{ title }}</span>
          <NSelect
            v-if="mode === 'sector' && sectorGroups.length"
            :value="activeSectorGroupId"
            :options="groupSelectOptions"
            size="small"
            class="group-select"
            @update:value="switchGroup"
          />
          <span
            v-if="mode === 'stock' && soloStockLabel"
            class="truncate text-[var(--primary)]"
          >· {{ soloStockLabel }}</span>
          <span
            v-if="mode === 'sector' && soloSectorLabel"
            class="truncate text-[var(--primary)]"
          >· {{ soloSectorLabel }}</span>
        </h2>
        <span class="shrink-0 text-xs text-[var(--muted)]">{{ countLabel }}</span>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <NButton v-if="mode === 'sector'" size="tiny" quaternary @click="boardStore.openPicker">
          管理分组
        </NButton>
        <IntradayDatePicker v-if="showDatePicker" :mode="mode" />
        <span
          v-else-if="mode === 'stock' && (sectorViewDate || board.sector_view_date)"
          class="linked-date-hint"
          title="个股日期跟随左侧板块"
        >
          {{ sectorViewDate || board.sector_view_date }}
        </span>
      </div>
    </div>

    <NSpin class="panel-spin" :show="showLoading" :delay="80" :description="loadingHint">
      <div
        class="panel-stack"
        :class="mode === 'sector' ? 'panel-stack--sector' : 'panel-stack--stock'"
      >
        <MarketScopePanel v-if="mode === 'sector'" />
        <div class="panel-body" :class="mode === 'sector' ? 'panel-body--sector' : 'panel-body--stock'">
          <FundFlowChart :mode="mode" />
          <FundRankPanel :mode="mode" />
        </div>
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
.group-select {
  width: min(188px, 34vw);
  min-width: 148px;
  flex-shrink: 0;
}

.linked-date-hint {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.group-select :deep(.n-base-selection) {
  --n-height: 26px;
  font-size: 12px;
}

.group-select :deep(.n-base-selection-label) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-spin {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.panel-spin :deep(.n-spin-container) {
  flex: 1;
  min-height: 0;
  height: 100%;
}

.panel-spin :deep(.n-spin-content) {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.panel-stack {
  display: flex;
  flex: 1;
  min-height: 0;
  height: 100%;
  flex-direction: column;
  gap: 8px;
}

.panel-stack--sector .panel-body {
  flex: 1;
  min-height: 240px;
}

.panel-body {
  display: grid;
  flex: 1;
  min-height: 0;
  height: 100%;
  gap: 8px;
}

/* 板块信息区：板块/明盘/暗盘/涨幅；个股信息区：个股/明盘/暗盘/净比/涨幅 */
.panel-body--sector {
  grid-template-columns: minmax(0, 1fr) minmax(336px, 38%);
}

.panel-body--stock {
  grid-template-columns: minmax(0, 1fr) minmax(340px, 42%);
}

.panel-spin :deep(.n-spin-description) {
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
}
</style>
