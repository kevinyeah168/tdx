<script setup lang="ts">
import FundFlowChart from '@/components/chart/FundFlowChart.vue'
import FundRankPanel from '@/components/common/FundRankPanel.vue'
import IntradayDatePicker from '@/components/common/IntradayDatePicker.vue'
import { NButton, NButtonGroup, NSpin } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useBoardStore } from '@/stores/boardStore'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const {
  board,
  sectorSourceMode,
  stockSourceMode,
  autoSectorCount,
  sectorLoading,
  sectorLoadingHint,
  stockLoading,
  stockLoadingHint,
} = storeToRefs(boardStore)

const title = computed(() => (props.mode === 'stock' ? '个股主力' : '板块资金走势'))
const count = computed(() =>
  props.mode === 'stock'
    ? board.value.stock_series?.length ?? 0
    : board.value.sector_series?.length ?? 0,
)

const showLoading = computed(() =>
  props.mode === 'stock' ? stockLoading.value : sectorLoading.value,
)

const loadingHint = computed(() => {
  if (props.mode === 'stock') return stockLoadingHint.value || '加载个股主力…'
  return sectorLoadingHint.value || '加载板块数据…'
})

function onSectorMode(mode: 'auto' | 'selected') {
  void boardStore.setSectorSourceMode(mode)
}

function onStockMode(mode: 'linkage' | 'selected') {
  void boardStore.setStockSourceMode(mode)
}
</script>

<template>
  <section class="flex h-full min-h-0 flex-col gap-2">
    <div class="flex shrink-0 items-center justify-between gap-2 px-1">
      <div class="flex min-w-0 items-center gap-2">
        <h2 class="m-0 text-sm font-600 text-[var(--text)]">{{ title }}</h2>
        <span class="text-xs text-[var(--muted)]">({{ count }})</span>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <NButtonGroup v-if="mode === 'sector'" size="tiny">
          <NButton
            :type="sectorSourceMode === 'auto' ? 'primary' : 'default'"
            :ghost="sectorSourceMode !== 'auto'"
            @click="onSectorMode('auto')"
          >
            流入前{{ autoSectorCount }}
          </NButton>
          <NButton
            :type="sectorSourceMode === 'selected' ? 'primary' : 'default'"
            :ghost="sectorSourceMode !== 'selected'"
            @click="onSectorMode('selected')"
          >
            自选
          </NButton>
        </NButtonGroup>
        <NButtonGroup v-else size="tiny">
          <NButton
            :type="stockSourceMode === 'linkage' ? 'primary' : 'default'"
            :ghost="stockSourceMode !== 'linkage'"
            @click="onStockMode('linkage')"
          >
            联动
          </NButton>
          <NButton
            :type="stockSourceMode === 'selected' ? 'primary' : 'default'"
            :ghost="stockSourceMode !== 'selected'"
            @click="onStockMode('selected')"
          >
            自选
          </NButton>
        </NButtonGroup>
        <NButton v-if="mode === 'sector'" size="tiny" quaternary @click="boardStore.openPicker">
          管理自选
        </NButton>
        <NButton v-else size="tiny" quaternary @click="boardStore.openStockPicker">
          管理自选
        </NButton>
        <IntradayDatePicker :mode="mode" />
      </div>
    </div>

    <NSpin class="panel-spin" :show="showLoading" :delay="80" :description="loadingHint">
      <div class="panel-body">
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
  grid-template-columns: minmax(0, 1fr) minmax(252px, 32%);
  gap: 8px;
}

.panel-spin :deep(.n-spin-description) {
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
}
</style>
