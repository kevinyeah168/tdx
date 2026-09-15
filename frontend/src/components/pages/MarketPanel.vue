<script setup lang="ts">
import FundFlowChart from '@/components/chart/FundFlowChart.vue'
import FundRankPanel from '@/components/common/FundRankPanel.vue'
import IntradayDatePicker from '@/components/common/IntradayDatePicker.vue'
import { NButton, NSpin } from 'naive-ui'
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
} = storeToRefs(boardStore)

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

const count = computed(() => {
  if (props.mode === 'stock') return board.value.stock_series?.length ?? 0
  return board.value.sector_series?.length ?? 0
})

const selectedTotal = computed(() => board.value.selected_boards?.length ?? 0)

const countLabel = computed(() => {
  if (props.mode === 'stock') return `(${count.value})`
  if (selectedTotal.value > count.value) return `(${count.value}/${selectedTotal.value})`
  return `(${count.value})`
})

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
          <span
            v-if="mode === 'stock' && soloStockLabel"
            class="truncate text-[var(--primary)]"
          >· {{ soloStockLabel }}</span>
        </h2>
        <span class="shrink-0 text-xs text-[var(--muted)]">{{ countLabel }}</span>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <NButton v-if="mode === 'sector'" size="tiny" quaternary @click="boardStore.openPicker">
          管理自选
        </NButton>
        <IntradayDatePicker :mode="mode" />
      </div>
    </div>

    <NSpin class="panel-spin" :show="showLoading" :delay="80" :description="loadingHint">
      <div class="panel-body" :class="mode === 'sector' ? 'panel-body--sector' : 'panel-body--stock'">
        <FundFlowChart :mode="mode" />
        <FundRankPanel :mode="mode" />
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
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

.panel-body {
  display: grid;
  flex: 1;
  min-height: 0;
  height: 100%;
  gap: 8px;
}

/* 板块信息区：板块/明盘/涨幅；个股信息区：个股/明盘/暗盘/净比/涨幅 */
.panel-body--sector {
  grid-template-columns: minmax(0, 1fr) minmax(300px, 38%);
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
