<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import {
  NButton,
  NCheckbox,
  NDatePicker,
  NEmpty,
  NInput,
  NScrollbar,
  NSelect,
  NSpin,
  NTag,
} from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import CycleReplayPlaybackBar from '@/components/workbench/CycleReplayPlaybackBar.vue'
import CycleReplayTrendChart from '@/components/workbench/CycleReplayTrendChart.vue'
import { searchSecurities } from '@/api/market'
import { searchSectors } from '@/api/sectors'
import { fetchSectorGroups } from '@/api/sectorGroups'
import { fetchStockGroups } from '@/api/stockGroups'
import {
  MAX_CYCLE_SECTOR,
  MAX_CYCLE_STOCK,
  useCycleReplayStore,
  type CycleReplayEntityMode,
} from '@/stores/cycleReplayStore'
import type { SectorSummary } from '@/types/api'
import type { FlowSeries } from '@/types/board'
import { seriesColor } from '@/utils/chartColors'
import {
  CYCLE_REPLAY_RANGE_PRESETS,
  type CycleReplayRangePresetKey,
} from '@/utils/cycleReplayRange'
import { isWeekdayDate } from '@/utils/tradingSession'
import { localDateFromTimestamp } from '@/utils/tradeDate'

const store = useCycleReplayStore()

const modeOptions = [
  { label: '板块回放', value: 'sector' },
  { label: '个股回放', value: 'stock' },
]

const sectorGroups = ref<{ label: string; value: string }[]>([])
const stockGroups = ref<{ label: string; value: string }[]>([])
const selectedGroupId = ref<string | null>(null)

const searchQuery = ref('')
const searchLoading = ref(false)
const sectorHits = ref<SectorSummary[]>([])
const stockHits = ref<{ symbol: string; name: string }[]>([])
const selectedHitIds = ref<Set<string>>(new Set())

const rangePresets = CYCLE_REPLAY_RANGE_PRESETS

const availableDateSet = computed(() => new Set(store.availableDates))

const dateRangeValue = computed<[string, string]>(() => [store.dateFrom, store.dateTo])

const groupOptions = computed(() =>
  store.entityMode === 'sector' ? sectorGroups.value : stockGroups.value,
)

const maxLabel = computed(() =>
  store.entityMode === 'sector' ? MAX_CYCLE_SECTOR : MAX_CYCLE_STOCK,
)

const chartTitle = computed(() => {
  const count = store.displaySeries.length
  if (!count) return '资金走势回放'
  return store.entityMode === 'sector'
    ? `板块主力累计趋势 (${count})`
    : `个股主力累计趋势 (${count})`
})

const selectedRows = computed(() => {
  const palette: FlowSeries[] = store.selected.map((entity) => ({
    id: entity.id,
    name: entity.name,
    cum_main: 0,
    values: [],
  }))
  const kind = store.entityMode === 'stock' ? 'stock' : 'sector'
  return store.selected.map((entity, index) => ({
    ...entity,
    color: seriesColor(palette, palette[index]!, kind),
  }))
})

function isDateDisabled(ts: number): boolean {
  const date = localDateFromTimestamp(ts)
  if (!isWeekdayDate(date)) return true
  if (!availableDateSet.value.size) return true
  return !availableDateSet.value.has(date)
}

async function onRangeChange(value: [string, string] | null) {
  if (!value || value.length !== 2 || !value[0] || !value[1]) return
  await store.setDateRange(value[0], value[1])
}

function applyPreset(key: CycleReplayRangePresetKey) {
  store.applyPreset(key)
}

async function loadGroups() {
  try {
    const [sectors, stocks] = await Promise.all([fetchSectorGroups(), fetchStockGroups()])
    sectorGroups.value = sectors.items.map((group) => ({
      label: `${group.name} (${group.sectors.length})`,
      value: group.id,
    }))
    stockGroups.value = stocks.items.map((group) => ({
      label: `${group.name} (${group.symbols.length})`,
      value: group.id,
    }))
  } catch {
    sectorGroups.value = []
    stockGroups.value = []
  }
}

const runSearch = useDebounceFn(async () => {
  const query = searchQuery.value.trim()
  selectedHitIds.value = new Set()
  if (!query) {
    sectorHits.value = []
    stockHits.value = []
    return
  }

  searchLoading.value = true
  try {
    if (store.entityMode === 'sector') {
      const response = await searchSectors(query, 40)
      sectorHits.value = response.items
      stockHits.value = []
    } else {
      const response = await searchSecurities(query)
      stockHits.value = response.results.map((item) => ({
        symbol: item.symbol,
        name: item.name,
      }))
      sectorHits.value = []
    }
  } catch {
    sectorHits.value = []
    stockHits.value = []
  } finally {
    searchLoading.value = false
  }
}, 280)

watch(searchQuery, () => {
  void runSearch()
})

watch(
  () => store.entityMode,
  () => {
    searchQuery.value = ''
    sectorHits.value = []
    stockHits.value = []
    selectedHitIds.value = new Set()
    selectedGroupId.value = store.sourceGroupId
  },
)

function toggleHit(id: string, checked: boolean) {
  const next = new Set(selectedHitIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedHitIds.value = next
}

function confirmSearchAdd() {
  if (store.entityMode === 'sector') {
    const entities = sectorHits.value
      .filter((item) => selectedHitIds.value.has(item.sector_id))
      .map((item) => ({ id: item.sector_id, name: item.name }))
    store.addEntities(entities)
  } else {
    const entities = stockHits.value
      .filter((item) => selectedHitIds.value.has(item.symbol))
      .map((item) => ({ id: item.symbol, name: item.name }))
    store.addEntities(entities)
  }
  selectedHitIds.value = new Set()
}

async function applyGroup() {
  if (!selectedGroupId.value) return
  await store.applyGroup(selectedGroupId.value)
  selectedGroupId.value = store.sourceGroupId
}

function onModeChange(mode: CycleReplayEntityMode) {
  store.setEntityMode(mode)
  selectedGroupId.value = store.sourceGroupId
}

onMounted(async () => {
  await store.loadAvailableDates()
  await loadGroups()
  store.initializeRange()
})

onBeforeUnmount(() => {
  store.stopTimer()
})
</script>

<template>
  <div class="cycle-replay-workspace">
    <header class="cycle-replay-toolbar panel-card">
      <div class="cycle-toolbar-row cycle-toolbar-main">
        <NSelect
          :value="store.entityMode"
          :options="modeOptions"
          size="small"
          class="cycle-mode-select"
          @update:value="onModeChange"
        />
        <NDatePicker
          :formatted-value="dateRangeValue"
          value-format="yyyy-MM-dd"
          type="daterange"
          size="small"
          class="cycle-date-range"
          :is-date-disabled="isDateDisabled"
          @update:formatted-value="onRangeChange"
        />
        <div class="cycle-preset-row">
          <NButton
            v-for="preset in rangePresets"
            :key="preset.key"
            size="tiny"
            :type="store.activePreset === preset.key ? 'primary' : 'default'"
            :disabled="store.presetDisabled(preset.key)"
            quaternary
            @click="applyPreset(preset.key)"
          >
            {{ preset.label }}
          </NButton>
        </div>
      </div>
      <div class="cycle-toolbar-row cycle-toolbar-meta">
        <span class="cycle-data-summary">{{ store.availableSummary }}</span>
        <span class="cycle-toolbar-hint">
          {{ store.rangeLabel }} · 每日收盘主力累计 · 悬停查看明细
        </span>
      </div>
    </header>

    <p v-if="store.rangeStatusHint" class="cycle-range-hint">{{ store.rangeStatusHint }}</p>
    <p v-if="store.error" class="cycle-error">{{ store.error }}</p>

    <div class="cycle-replay-body">
      <aside class="cycle-sidebar panel-card">
        <section class="cycle-sidebar-section">
          <h3 class="cycle-sidebar-title">从分组载入</h3>
          <NSelect
            v-model:value="selectedGroupId"
            :options="groupOptions"
            size="small"
            placeholder="选择分组"
            clearable
          />
          <NButton
            size="small"
            type="primary"
            block
            :disabled="!selectedGroupId"
            :loading="store.loading"
            @click="applyGroup"
          >
            应用分组
          </NButton>
        </section>

        <section class="cycle-sidebar-section">
          <h3 class="cycle-sidebar-title">搜索添加</h3>
          <NInput
            v-model:value="searchQuery"
            size="small"
            :placeholder="store.entityMode === 'sector' ? '搜索板块' : '搜索个股'"
            clearable
          />
          <div v-if="searchLoading" class="cycle-search-loading">搜索中…</div>
          <div v-else-if="store.entityMode === 'sector' && sectorHits.length" class="cycle-search-list">
            <label
              v-for="item in sectorHits"
              :key="item.sector_id"
              class="cycle-search-item"
            >
              <NCheckbox
                :checked="selectedHitIds.has(item.sector_id)"
                @update:checked="(checked) => toggleHit(item.sector_id, checked)"
              />
              <span class="cycle-search-name">{{ item.name }}</span>
              <span class="cycle-search-id">{{ item.sector_id }}</span>
            </label>
          </div>
          <div v-else-if="store.entityMode === 'stock' && stockHits.length" class="cycle-search-list">
            <label
              v-for="item in stockHits"
              :key="item.symbol"
              class="cycle-search-item"
            >
              <NCheckbox
                :checked="selectedHitIds.has(item.symbol)"
                @update:checked="(checked) => toggleHit(item.symbol, checked)"
              />
              <span class="cycle-search-name">{{ item.name }}</span>
              <span class="cycle-search-id">{{ item.symbol }}</span>
            </label>
          </div>
          <NButton
            size="small"
            block
            :disabled="!selectedHitIds.size"
            @click="confirmSearchAdd"
          >
            确认添加 ({{ selectedHitIds.size }})
          </NButton>
        </section>

        <section class="cycle-sidebar-section cycle-selected-section">
          <div class="cycle-selected-header">
            <div class="cycle-selected-heading">
              <h3 class="cycle-sidebar-title">已选</h3>
              <span class="cycle-selected-count">{{ store.selected.length }}/{{ maxLabel }}</span>
            </div>
            <button
              v-if="store.selected.length"
              type="button"
              class="cycle-clear-btn"
              @click="store.clearSelection"
            >
              清空
            </button>
          </div>
          <div v-if="!store.selected.length" class="cycle-empty-hint">
            选择分组或搜索添加板块/个股
          </div>
          <NScrollbar v-else class="cycle-selected-scroll" trigger="none">
            <ul class="cycle-selected-list">
              <li
                v-for="item in selectedRows"
                :key="item.id"
                class="cycle-selected-item"
              >
                <span class="cycle-selected-dot" :style="{ backgroundColor: item.color }" />
                <span class="cycle-selected-name" :title="item.name">{{ item.name }}</span>
                <span class="cycle-selected-id num">{{ item.id }}</span>
                <button
                  type="button"
                  class="cycle-selected-remove"
                  title="移除"
                  @click="store.removeEntity(item.id)"
                >
                  ×
                </button>
              </li>
            </ul>
          </NScrollbar>
        </section>
      </aside>

      <div class="cycle-main">
        <div class="cycle-chart-card panel-card">
          <div class="cycle-chart-header">
            <div class="cycle-chart-heading">
              <h2 class="cycle-chart-title">{{ chartTitle }}</h2>
              <span v-if="store.displaySeries.length > 10" class="cycle-chart-note">
                曲线较多，悬停图表查看数值
              </span>
            </div>
            <div class="cycle-chart-badges">
              <NTag size="small" :bordered="false">{{ store.rangeLabel }}</NTag>
              <NTag v-if="store.frames.length" size="small" type="info" :bordered="false">
                {{ store.cursorDate }}
              </NTag>
            </div>
          </div>
          <NSpin :show="store.loading" class="cycle-chart-spin">
            <div class="cycle-chart-body">
              <CycleReplayTrendChart
                v-if="store.displaySeries.length && store.displayTimeline.length"
                :series="store.displaySeries"
                :date-timeline="store.displayTimeline"
                :cursor-index="store.frames.length ? store.frameIndex : null"
              />
              <NEmpty
                v-else
                class="cycle-chart-empty"
                :description="store.selected.length ? '正在加载或无曲线数据' : '请从左侧选择板块或个股'"
              />
            </div>
          </NSpin>
          <CycleReplayPlaybackBar v-if="store.frames.length" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cycle-replay-workspace {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.cycle-replay-toolbar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 12px;
  flex-shrink: 0;
}

.cycle-toolbar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.cycle-toolbar-meta {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.cycle-mode-select {
  width: 112px;
}

.cycle-date-range {
  width: 248px;
}

.cycle-preset-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.cycle-data-summary {
  font-size: 12px;
  color: var(--text-secondary, var(--muted));
  flex-shrink: 0;
}

.cycle-toolbar-hint {
  font-size: 12px;
  color: var(--muted);
  margin-left: auto;
}

.cycle-range-hint {
  margin: 0;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  color: var(--warning, #b45309);
  background: color-mix(in srgb, var(--warning, #f59e0b) 10%, transparent);
}

.cycle-error {
  margin: 0;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  color: var(--danger, #dc2626);
  background: color-mix(in srgb, var(--danger, #dc2626) 8%, transparent);
}

.cycle-replay-body {
  display: grid;
  grid-template-columns: minmax(240px, 272px) minmax(0, 1fr);
  gap: 8px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.cycle-sidebar {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 10px;
  min-height: 0;
  overflow: hidden;
}

.cycle-sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  padding-bottom: 10px;
}

.cycle-sidebar-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.cycle-search-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 180px;
  overflow: auto;
  padding: 4px 0;
}

.cycle-search-item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 6px;
  padding: 4px 2px;
  font-size: 12px;
  cursor: pointer;
}

.cycle-search-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cycle-search-id {
  color: var(--muted);
  font-size: 11px;
}

.cycle-search-loading {
  font-size: 12px;
  color: var(--muted);
}

.cycle-selected-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 2px;
  padding-top: 10px;
  padding-bottom: 0;
  border-top: 1px solid color-mix(in srgb, var(--border) 65%, transparent);
}

.cycle-selected-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}

.cycle-selected-heading {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.cycle-selected-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  padding: 1px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 8%, var(--panel));
  white-space: nowrap;
}

.cycle-clear-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  flex-shrink: 0;
}

.cycle-clear-btn:hover {
  color: var(--danger, #dc2626);
}

.cycle-selected-scroll {
  flex: 1;
  min-height: 0;
}

.cycle-selected-scroll :deep(.n-scrollbar-content) {
  padding-right: 4px;
}

.cycle-selected-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cycle-selected-item {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto 20px;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 0 4px 0 6px;
  border-radius: 6px;
  font-size: 12px;
  transition: background-color 0.12s ease;
}

.cycle-selected-item:hover {
  background: color-mix(in srgb, var(--accent) 6%, var(--panel));
}

.cycle-selected-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.cycle-selected-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.cycle-selected-id {
  font-size: 10px;
  color: var(--muted);
  max-width: 64px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cycle-selected-remove {
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: var(--muted);
  border-radius: 4px;
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.cycle-selected-remove:hover {
  color: var(--danger, #dc2626);
  background: color-mix(in srgb, var(--danger, #dc2626) 10%, transparent);
}

.cycle-empty-hint {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
  padding: 4px 2px 0;
}

.cycle-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.cycle-chart-card {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 10px 12px 12px;
  overflow: hidden;
}

.cycle-chart-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  flex-shrink: 0;
}

.cycle-chart-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cycle-chart-note {
  font-size: 11px;
  color: var(--muted);
}

.cycle-chart-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.cycle-chart-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.cycle-chart-spin {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.cycle-chart-spin :deep(.n-spin-content) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.cycle-chart-body {
  flex: 1;
  min-height: 280px;
  display: flex;
  flex-direction: column;
}

.cycle-chart-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 960px) {
  .cycle-replay-body {
    grid-template-columns: 1fr;
  }
}
</style>
