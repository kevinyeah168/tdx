<script setup lang="ts">
import FundFlowChart from '@/components/chart/FundFlowChart.vue'
import FundRankPanel from '@/components/common/FundRankPanel.vue'
import IntradayDatePicker from '@/components/common/IntradayDatePicker.vue'
import MarketScopePanel from '@/components/workbench/MarketScopePanel.vue'
import { ChevronDownOutline } from '@vicons/ionicons5'
import { NButton, NDropdown, NIcon, NSpin } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import type { SectorGroup } from '@/api/sectorGroups'

const MAX_VISIBLE_SECTOR_GROUPS = 6

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

/** 首页板块日期由顶栏 ReplayControls 统一控制；个股自选模式仍保留独立日期。 */
const showDatePicker = computed(
  () => props.mode === 'stock' && stockSourceMode.value !== 'linkage',
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

function switchGroup(groupId: string) {
  void boardStore.switchSectorGroup(groupId)
}

function pickOverflowGroup(key: string | number) {
  switchGroup(String(key))
}

/** 最多展示 6 个；当前选中若在溢出区则替换最后一个 Tab 以保证可见。 */
const visibleSectorGroups = computed((): SectorGroup[] => {
  const groups = sectorGroups.value
  if (groups.length <= MAX_VISIBLE_SECTOR_GROUPS) return groups

  const activeId = activeSectorGroupId.value
  const activeIndex = groups.findIndex((group) => group.id === activeId)
  if (activeIndex < 0 || activeIndex < MAX_VISIBLE_SECTOR_GROUPS) {
    return groups.slice(0, MAX_VISIBLE_SECTOR_GROUPS)
  }

  const head = groups.slice(0, MAX_VISIBLE_SECTOR_GROUPS - 1)
  const active = groups[activeIndex]
  return active ? [...head, active] : groups.slice(0, MAX_VISIBLE_SECTOR_GROUPS)
})

const overflowSectorGroups = computed(() => {
  const visibleIds = new Set(visibleSectorGroups.value.map((group) => group.id))
  return sectorGroups.value.filter((group) => !visibleIds.has(group.id))
})

const overflowDropdownOptions = computed(() =>
  overflowSectorGroups.value.map((group) => ({
    label: `${group.name} (${group.sector_ids.length})`,
    key: group.id,
  })),
)

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
    <div class="panel-header">
      <div class="panel-header-left">
        <h2 class="panel-title">
          <span class="truncate">{{ title }}</span>
          <span
            v-if="mode === 'stock' && soloStockLabel"
            class="truncate text-[var(--primary)]"
          >· {{ soloStockLabel }}</span>
          <span
            v-if="mode === 'sector' && soloSectorLabel"
            class="truncate text-[var(--primary)]"
          >· {{ soloSectorLabel }}</span>
        </h2>
        <span class="panel-count">{{ countLabel }}</span>
      </div>

      <div v-if="mode === 'sector' && sectorGroups.length" class="group-tabs">
        <button
          v-for="group in visibleSectorGroups"
          :key="group.id"
          type="button"
          class="group-tab"
          :class="{ active: activeSectorGroupId === group.id }"
          :disabled="sectorLoading"
          :title="group.name"
          @click="switchGroup(group.id)"
        >
          <span class="group-tab-name">{{ group.name }}</span>
          <span class="group-count">{{ group.sector_ids.length }}</span>
        </button>
        <NDropdown
          v-if="overflowSectorGroups.length"
          trigger="click"
          placement="bottom"
          :options="overflowDropdownOptions"
          @select="pickOverflowGroup"
        >
          <button
            type="button"
            class="group-tab group-tab-more"
            :disabled="sectorLoading"
          >
            更多
            <span class="group-count">{{ overflowSectorGroups.length }}</span>
            <NIcon :component="ChevronDownOutline" :size="14" />
          </button>
        </NDropdown>
      </div>

      <div class="panel-header-right">
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
.panel-header {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 10px;
  min-height: 32px;
  padding: 0 4px;
}

.panel-header-left {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.panel-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.panel-count {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--muted);
}

.panel-header-right {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
}

.group-tabs {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 6px;
  overflow: hidden;
}

.group-tab {
  display: inline-flex;
  flex-shrink: 1;
  min-width: 0;
  max-width: 120px;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease,
    color 0.15s ease;
}

.group-tab-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-tab-more {
  flex-shrink: 0;
  max-width: none;
}

.group-tab:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
  color: var(--text);
}

.group-tab.active {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
  color: var(--accent);
  font-weight: 600;
}

.group-tab:disabled {
  cursor: wait;
  opacity: 0.65;
}

.group-count {
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  opacity: 0.8;
}

.linked-date-hint {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
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
