<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import {
  NAutoComplete,
  NButton,
  NDropdown,
  NEmpty,
  NInput,
  NModal,
  NSpin,
  NVirtualList,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'

import { apiGet } from '@/api/client'
import SessionSkeleton from '@/components/workbench/SessionSkeleton.vue'
import StockGroupBatchImport from '@/components/workbench/StockGroupBatchImport.vue'
import StockListRow from '@/components/workbench/StockListRow.vue'
import StockMultiFundChart from '@/components/workbench/StockMultiFundChart.vue'
import { useReplayStore } from '@/stores/replayStore'
import { MAX_CHART_STOCKS, useStockStore, type StockListItem } from '@/stores/stockStore'
import type { SearchResponse } from '@/types/api'
import { seriesColor } from '@/utils/chartColors'
import { todayTradeDate } from '@/utils/tradeDate'

const props = defineProps<{
  initialSymbol?: string
}>()

const emit = defineEmits<{
  openSettings: []
}>()

const stockStore = useStockStore()
const replayStore = useReplayStore()
const {
  filteredListItems,
  chartSeries,
  soloSeries,
  chartSymbols,
  highlightedSymbol,
  listLoading,
  chartLoading,
  hasChartData,
  selectedCount,
  isSoloMode,
  groups,
  activeGroup,
} = storeToRefs(stockStore)

const searchOptions = ref<{ label: string; value: string }[]>([])
const virtualListRef = ref<InstanceType<typeof NVirtualList> | null>(null)
const quickCreateOpen = ref(false)
const batchImportOpen = ref(false)
const newGroupName = ref('')
const creatingGroup = ref(false)
const createError = ref('')

const isCustomGroup = computed(() => stockStore.activeGroupId !== 'all')

const groupDropdownOptions = computed(() =>
  groups.value.map((group) => ({
    key: group.id,
    label: group.name,
  })),
)

const searchPlaceholder = computed(() =>
  isCustomGroup.value ? '搜索筛选或点选加入分组' : '搜索筛选或点选叠加曲线',
)

const emptyDescription = computed(() => {
  if (isCustomGroup.value) return '分组为空，请搜索添加个股'
  return '无匹配个股'
})

const chartColorMap = computed(() => {
  const map = new Map<string, string>()
  chartSeries.value.forEach((series) => {
    map.set(series.id, seriesColor(chartSeries.value, series, 'stock'))
  })
  return map
})

const chartTitle = computed(() => {
  if (isSoloMode.value && soloSeries.value) {
    return `${soloSeries.value.name} · Solo`
  }
  if (!selectedCount.value) return '个股主力净额'
  return `个股主力净额 · 已选 ${selectedCount.value}/${MAX_CHART_STOCKS}`
})

const chartSub = computed(() => {
  if (isSoloMode.value) {
    return '明盘 / 暗盘 / 均价 / 价格；点击「返回多股」回到叠加视图'
  }
  return `勾选个股叠加显示；点击曲线或末端标签进入 Solo（最多 ${MAX_CHART_STOCKS} 条）`
})

const soloLegend = [
  { label: '明盘', color: '#2563eb' },
  { label: '暗盘', color: '#9333ea' },
  { label: '均价', color: '#d97706', dashed: false },
  { label: '价格', color: '#64748b', dashed: true },
]

const runRemoteSearch = useDebounceFn(async (value: string) => {
  const trimmed = value.trim()
  if (trimmed.length < 2) {
    searchOptions.value = []
    return
  }
  try {
    const response = await apiGet<SearchResponse>('/api/v1/market/search', { q: trimmed })
    searchOptions.value = response.results.map((item) => ({
      label: `${item.symbol} ${item.name}`,
      value: item.symbol,
    }))
  } catch {
    searchOptions.value = []
  }
}, 250)

function onSearchInput(value: string) {
  stockStore.searchQuery = value
  void runRemoteSearch(value)
}

function scrollToSymbol(symbol: string) {
  const normalized = symbol.toUpperCase()
  const index = filteredListItems.value.findIndex((item) => item.symbol === normalized)
  if (index < 0 || !virtualListRef.value) return
  virtualListRef.value.scrollTo({ index, debounce: false })
}

async function onSearchSelect(symbol: string) {
  searchOptions.value = []
  stockStore.searchQuery = ''

  if (isCustomGroup.value && activeGroup.value) {
    await stockStore.addSymbolToGroup(activeGroup.value.id, symbol)
    requestAnimationFrame(() => scrollToSymbol(symbol))
    return
  }

  const normalized = stockStore.addSymbol(symbol)
  void stockStore.loadChartData()
  requestAnimationFrame(() => scrollToSymbol(normalized))
}

function onToggle(symbol: string, checked: boolean) {
  stockStore.selectForChart(symbol, checked)
  void stockStore.loadChartData()
}

function onEnterSolo(symbol: string) {
  void stockStore.enterSolo(symbol)
  scrollToSymbol(symbol)
}

function chartColorFor(item: StockListItem): string | undefined {
  return chartColorMap.value.get(item.symbol)
}

function addFocusedToGroup(groupId: string) {
  if (!highlightedSymbol.value) return
  void stockStore.addSymbolToGroup(groupId, highlightedSymbol.value)
}

function removeFromActiveGroup(symbol: string) {
  if (!activeGroup.value) return
  void stockStore.removeSymbolFromGroup(activeGroup.value.id, symbol)
}

async function createGroup() {
  const name = newGroupName.value.trim()
  if (!name) {
    createError.value = '请输入分组名称'
    return
  }
  creatingGroup.value = true
  createError.value = ''
  try {
    await stockStore.createGroup(name)
    newGroupName.value = ''
    quickCreateOpen.value = false
  } catch (error) {
    createError.value = error instanceof Error ? error.message : String(error)
  } finally {
    creatingGroup.value = false
  }
}

function onBatchImported() {
  void stockStore.loadGroups()
}

async function addSelectedToGroup() {
  if (!activeGroup.value || !chartSymbols.value.length) return
  await stockStore.addSymbolsToGroup(activeGroup.value.id, chartSymbols.value)
}

watch(
  () => [props.initialSymbol, replayStore.tradeDate, replayStore.minute] as const,
  ([symbol, tradeDate, minute]) => {
    if (!stockStore.bootstrapped) {
      void stockStore.bootstrap(symbol ?? '', tradeDate, minute)
      return
    }
    stockStore.setReplayContext(tradeDate, minute)
    if (symbol) {
      const normalized = stockStore.addSymbol(symbol)
      void stockStore.loadChartData()
      requestAnimationFrame(() => scrollToSymbol(normalized))
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="stock-workspace">
    <aside class="panel-card stock-sidebar">
      <div class="stock-sidebar-head">
        <div class="sidebar-title-row">
          <p class="m-0 text-sm font-600">个股列表</p>
          <NButton size="tiny" quaternary @click="emit('openSettings')">管理分组</NButton>
        </div>

        <div class="group-tabs">
          <button
            type="button"
            class="group-tab"
            :class="{ active: stockStore.activeGroupId === 'all' }"
            @click="void stockStore.setActiveGroup('all')"
          >
            全部
          </button>
          <button
            v-for="group in groups"
            :key="group.id"
            type="button"
            class="group-tab"
            :class="{ active: stockStore.activeGroupId === group.id }"
            @click="void stockStore.setActiveGroup(group.id)"
          >
            {{ group.name }}
            <span class="group-count">{{ group.symbol_ids.length }}</span>
          </button>
          <button type="button" class="group-tab group-tab-add" title="新建分组" @click="quickCreateOpen = true">
            +
          </button>
        </div>

        <NAutoComplete
          v-model:value="stockStore.searchQuery"
          class="search-box"
          :options="searchOptions"
          :placeholder="searchPlaceholder"
          clearable
          size="small"
          @update:value="onSearchInput"
          @select="onSearchSelect"
        />

        <div v-if="isCustomGroup" class="sidebar-actions">
          <NButton size="tiny" quaternary @click="batchImportOpen = true">批量导入</NButton>
          <NButton
            v-if="chartSymbols.length"
            size="tiny"
            quaternary
            @click="addSelectedToGroup"
          >
            加入已选 {{ chartSymbols.length }}
          </NButton>
        </div>
        <div v-else class="sidebar-actions">
          <NButton size="tiny" quaternary @click="stockStore.applyGroupChartSelection()">
            选 TOP {{ MAX_CHART_STOCKS }}
          </NButton>
          <NButton size="tiny" quaternary @click="stockStore.clearChartSelection()">清空曲线</NButton>
        </div>
      </div>

      <div class="stock-sidebar-body">
        <NSpin :show="listLoading || stockStore.groupsLoading" class="stock-list-spin">
          <NVirtualList
            v-if="filteredListItems.length"
            ref="virtualListRef"
            class="stock-virtual-list"
            :items="filteredListItems"
            :item-size="54"
            :item-resizable="false"
            key-field="symbol"
          >
            <template #default="{ item }">
              <div class="stock-item-wrap">
                <StockListRow
                  :item="item"
                  :chart-selected="chartSymbols.includes(item.symbol)"
                  :chart-color="chartColorFor(item)"
                  :focused="highlightedSymbol === item.symbol || stockStore.soloSymbol === item.symbol"
                  @toggle="(checked) => onToggle(item.symbol, checked)"
                  @focus="onEnterSolo(item.symbol)"
                />
                <button
                  v-if="isCustomGroup"
                  type="button"
                  class="stock-remove"
                  title="从分组移除"
                  @click.stop="removeFromActiveGroup(item.symbol)"
                >
                  ×
                </button>
                <NDropdown
                  v-else-if="groups.length && highlightedSymbol === item.symbol"
                  trigger="click"
                  :options="groupDropdownOptions"
                  @select="addFocusedToGroup"
                >
                  <button type="button" class="stock-add-group" title="加入分组">+</button>
                </NDropdown>
              </div>
            </template>
          </NVirtualList>
          <NEmpty
            v-else
            class="py-8"
            size="small"
            :description="emptyDescription"
          />
        </NSpin>
      </div>
    </aside>

    <section class="stock-main">
      <div class="chart-card panel-card">
        <div class="chart-toolbar">
          <div>
            <p class="chart-title">{{ chartTitle }}</p>
            <p class="chart-sub">{{ chartSub }}</p>
          </div>
          <div v-if="isSoloMode" class="chart-toolbar-right">
            <div class="solo-legend">
              <span v-for="item in soloLegend" :key="item.label" class="solo-legend-item">
                <span
                  class="solo-legend-line"
                  :class="{ dashed: item.dashed }"
                  :style="{ backgroundColor: item.dashed ? 'transparent' : item.color, borderColor: item.color }"
                />
                {{ item.label }}
              </span>
            </div>
            <NButton size="small" quaternary @click="stockStore.exitSolo()">返回多股</NButton>
          </div>
        </div>

        <SessionSkeleton
          v-if="!isSoloMode && !hasChartData && !chartLoading && selectedCount === 0"
          class="chart-skeleton"
          :trade-date="stockStore.tradeDate"
          title="请勾选个股查看曲线"
          message="从左侧列表勾选一只或多只个股，主力净额分时将叠加显示在此处。"
        />

        <SessionSkeleton
          v-else-if="!isSoloMode && !hasChartData && !chartLoading"
          class="chart-skeleton"
          :trade-date="stockStore.tradeDate"
          :title="stockStore.tradeDate === todayTradeDate() ? '今日尚未开盘' : '该交易日暂无数据'"
        />

        <div v-else class="chart-body">
          <NSpin :show="chartLoading" class="chart-spin">
            <StockMultiFundChart
              v-if="isSoloMode && soloSeries"
              mode="solo"
              :series="[]"
              :solo-series="soloSeries"
              class="chart-canvas"
            />
            <StockMultiFundChart
              v-else-if="!isSoloMode && chartSeries.length"
              mode="multi"
              :series="chartSeries"
              class="chart-canvas"
              @enter-solo="onEnterSolo"
            />
            <NEmpty
              v-else
              class="chart-empty"
              :description="
                isSoloMode
                  ? stockStore.chartError || '该个股暂无分钟数据'
                  : stockStore.chartError || '该交易日暂无分钟资金数据'
              "
            />
          </NSpin>
        </div>
      </div>
    </section>

    <NModal v-model:show="quickCreateOpen" preset="card" title="新建个股分组" style="width: 380px">
      <div class="manage-block">
        <p class="hint">分组保存在 Workbench 元数据库。批量管理请前往设置页。</p>
        <div class="manage-row">
          <NInput v-model:value="newGroupName" placeholder="分组名称" @keyup.enter="createGroup" />
          <NButton type="primary" :loading="creatingGroup" @click="createGroup">创建</NButton>
        </div>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <NButton quaternary size="small" @click="emit('openSettings')">打开设置 · 个股分组</NButton>
      </div>
    </NModal>

    <StockGroupBatchImport
      v-if="activeGroup"
      v-model:show="batchImportOpen"
      :group-id="activeGroup.id"
      :existing-count="activeGroup.symbol_ids.length"
      @imported="onBatchImported"
    />
  </div>
</template>

<style scoped>
.stock-workspace {
  display: grid;
  height: 100%;
  min-height: 0;
  gap: 6px;
  grid-template-columns: 300px minmax(0, 1fr);
}

.stock-sidebar {
  display: flex;
  min-height: 0;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
}

.stock-sidebar-head {
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
}

.sidebar-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.group-tabs {
  display: flex;
  gap: 6px;
  margin-top: 10px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.group-tab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
}

.group-tab.active {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
  color: var(--accent);
}

.group-tab-add {
  width: 28px;
  justify-content: center;
  padding-inline: 0;
}

.group-count {
  font-size: 10px;
  opacity: 0.75;
}

.search-box {
  margin-top: 8px;
  width: 100%;
}

.sidebar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.manage-block {
  display: grid;
  gap: 10px;
}

.manage-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.4;
}

.error-text {
  margin: 0;
  font-size: 12px;
  color: var(--danger, #dc2626);
}

.stock-sidebar-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.stock-list-spin {
  height: 100%;
}

:deep(.stock-list-spin .n-spin-container),
:deep(.stock-list-spin .n-spin-content) {
  height: 100%;
}

.stock-virtual-list {
  height: 100%;
  max-height: 100%;
}

.stock-item-wrap {
  display: flex;
  align-items: stretch;
  gap: 2px;
}

.stock-item-wrap :deep(.stock-item) {
  flex: 1;
  min-width: 0;
}

.stock-remove,
.stock-add-group {
  flex-shrink: 0;
  width: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.stock-remove:hover,
.stock-add-group:hover {
  background: color-mix(in srgb, var(--accent) 10%, var(--panel));
  color: var(--accent);
}

.stock-main {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex: 1;
}

.chart-card {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  padding: 10px 12px;
}

.chart-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  margin-bottom: 8px;
}

.chart-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.chart-sub {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--muted);
}

.chart-toolbar-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.solo-legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.solo-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--muted);
}

.solo-legend-line {
  width: 14px;
  height: 2px;
  border-radius: 1px;
}

.solo-legend-line.dashed {
  height: 0;
  border-top: 2px dashed;
}

.chart-body,
.chart-spin,
.chart-skeleton {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

:deep(.chart-spin .n-spin-container),
:deep(.chart-spin .n-spin-content) {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.chart-canvas {
  flex: 1;
  min-height: 320px;
  cursor: pointer;
}

.chart-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
}

@media (max-width: 1024px) {
  .stock-workspace {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .stock-sidebar {
    max-height: 360px;
  }
}
</style>
