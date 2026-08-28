<script setup lang="ts">
import {
  NButton,
  NDataTable,
  NEmpty,
  NInput,
  NSpin,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h, ref } from 'vue'

import FundTierSelector from '@/components/workbench/FundTierSelector.vue'
import MemberListDrawer, { type MemberListKind } from '@/components/workbench/MemberListDrawer.vue'
import SectorHeader, { type StatKind } from '@/components/workbench/SectorHeader.vue'
import SessionSkeleton from '@/components/workbench/SessionSkeleton.vue'
import StockFundChart from '@/components/workbench/StockFundChart.vue'
import { useSectorStore, type SectorTypeFilter } from '@/stores/sectorStore'
import { fmtMoneyCompact, fmtPct, chgTone, toneClass } from '@/utils/format'
import { todayTradeDate } from '@/utils/tradeDate'
import type { SectorMemberRankItem } from '@/api/sectors'

const emit = defineEmits<{
  openStock: [symbol: string]
}>()

const sectorStore = useSectorStore()
const {
  selected,
  filteredItems,
  fundFlow,
  memberRanks,
  breadth,
  fundLoading,
  membersLoading,
  latestMainFlow,
  hasSessionData,
} = storeToRefs(sectorStore)

const selectedTiers = ref(['main'])
const drawerOpen = ref(false)
const drawerKind = ref<MemberListKind | null>(null)

const drawerTitle = computed(() => {
  const map: Record<MemberListKind, string> = {
    limit_up: '涨停个股',
    limit_down: '跌停个股',
    up: '上涨个股',
    down: '下跌个股',
  }
  return drawerKind.value ? map[drawerKind.value] : ''
})

const drawerItems = computed((): SectorMemberRankItem[] => {
  if (!drawerKind.value || !breadth.value) return []
  return breadth.value[drawerKind.value] ?? []
})

function openMemberList(kind: StatKind) {
  drawerKind.value = kind
  drawerOpen.value = true
}

const typeTabs: { key: SectorTypeFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'industry', label: '行业' },
  { key: 'concept', label: '概念' },
]

const memberColumns = [
  {
    title: '个股',
    key: 'name',
    minWidth: 88,
    ellipsis: { tooltip: true },
    render: (row: { symbol: string; name: string }) =>
      h('div', { class: 'min-w-0' }, [
        h('div', { class: 'truncate text-xs font-500' }, row.name),
        h('div', { class: 'num text-[10px] text-[var(--muted)]' }, row.symbol),
      ]),
  },
  {
    title: '主力',
    key: 'main_cumulative',
    width: 92,
    align: 'right' as const,
    render: (row: { main_cumulative: number }) =>
      h(
        'span',
        { class: `num money-cell text-[11px] font-600 ${toneClass(chgTone(row.main_cumulative))}` },
        fmtMoneyCompact(row.main_cumulative),
      ),
  },
  {
    title: '涨跌',
    key: 'change_pct',
    width: 58,
    align: 'right' as const,
    render: (row: { change_pct: number }) =>
      h(
        'span',
        { class: `num money-cell text-[11px] ${toneClass(chgTone(row.change_pct))}` },
        fmtPct(row.change_pct),
      ),
  },
]

const headerTime = computed(() => {
  const date = sectorStore.tradeDate.replace(/-/g, '/')
  if (!hasSessionData.value) return date
  const minute = fundFlow.value?.latest_complete_minute || sectorStore.replayMinute
  return `${date} ${minute}`
})
</script>

<template>
  <div class="sector-workspace">
    <!-- 左栏：板块列表 -->
    <aside class="panel-card sector-sidebar">
      <div class="sector-sidebar-head">
        <p class="m-0 text-sm font-600">板块列表</p>
        <div class="mt-2 flex flex-wrap gap-1">
          <NButton
            v-for="tab in typeTabs"
            :key="tab.key"
            size="tiny"
            :type="sectorStore.typeFilter === tab.key ? 'primary' : 'default'"
            @click="sectorStore.typeFilter = tab.key"
          >
            {{ tab.label }}
          </NButton>
        </div>
        <NInput
          v-model:value="sectorStore.searchQuery"
          class="mt-2"
          size="small"
          placeholder="搜索板块名称或代码"
          clearable
        />
      </div>
      <div class="sector-sidebar-body">
        <NSpin :show="sectorStore.loading" class="sector-list-spin">
          <div class="sector-list">
            <button
              v-for="sector in filteredItems"
              :key="sector.sector_id"
              type="button"
              class="sector-item"
              :class="{ active: sector.sector_id === sectorStore.selectedId }"
              @click="sectorStore.selectSector(sector.sector_id)"
            >
              <span class="truncate text-sm font-500">{{ sector.name }}</span>
              <span class="num text-[10px] text-[var(--muted)]">
                {{ sector.sector_id }} · {{ sector.member_count }} 成分
              </span>
            </button>
            <NEmpty v-if="!filteredItems.length" class="py-8" description="无匹配板块" size="small" />
          </div>
        </NSpin>
      </div>
    </aside>

    <!-- 主区 -->
    <section class="sector-main">
      <NSpin :show="fundLoading && hasSessionData">
        <SectorHeader
          v-if="selected"
          :sector-name="selected.name"
          :sector-type="selected.sector_type"
          :sector-id="selected.sector_id"
          :member-count="selected.member_count"
          :header-time="headerTime"
          :change-pct="fundFlow?.change_pct"
          :main-flow="latestMainFlow"
          :counts="breadth?.counts ?? null"
          :empty="!hasSessionData"
          @open-list="openMemberList"
        />
        <NEmpty v-else class="panel-card py-6" description="请从左侧选择板块" />
      </NSpin>

      <MemberListDrawer
        v-model:show="drawerOpen"
        :kind="drawerKind"
        :title="`${selected?.name ?? ''} · ${drawerTitle}`"
        :items="drawerItems"
        @open-stock="emit('openStock', $event)"
      />

      <!-- 曲线 + 成分股 3:1 同行（无数据时也保留布局） -->
      <div v-if="selected" class="chart-members-row panel-card">
        <div class="chart-pane">
          <div class="chart-toolbar">
            <span class="chart-title">主力净额分时</span>
            <FundTierSelector v-if="hasSessionData" v-model="selectedTiers" />
          </div>

          <SessionSkeleton
            v-if="!hasSessionData"
            class="chart-skeleton"
            :trade-date="sectorStore.tradeDate"
            :title="sectorStore.tradeDate === todayTradeDate() ? '今日尚未开盘' : '该交易日暂无数据'"
          />

          <div v-else class="chart-body">
            <NSpin :show="fundLoading" class="chart-spin">
              <StockFundChart
                v-if="fundFlow?.points.length"
                :payload="fundFlow"
                :tiers="selectedTiers"
                class="chart-canvas"
              />
              <NEmpty
                v-else
                class="chart-empty"
                :description="sectorStore.fundError || '该交易日暂无板块分钟资金数据'"
              />
            </NSpin>
          </div>
        </div>

        <aside class="members-pane">
          <div class="members-head">
            <p class="m-0 text-sm font-600">成分股</p>
            <p class="mt-0.5 text-[10px] text-[var(--muted)]">
              主力累计降序 · 共 {{ memberRanks.length || selected?.member_count || 0 }} 只
            </p>
          </div>
          <div class="members-body">
            <NSpin :show="membersLoading && hasSessionData" class="members-spin">
              <NDataTable
                v-if="memberRanks.length"
                :columns="memberColumns"
                :data="memberRanks"
                :bordered="false"
                size="small"
                flex-height
                :single-line="false"
                class="members-table"
                :row-props="(row) => ({ style: 'cursor: pointer', onClick: () => emit('openStock', row.symbol) })"
              />
              <NEmpty
                v-else
                :description="hasSessionData ? '暂无成分股数据' : '等待行情数据更新'"
                size="small"
                class="py-8"
              />
            </NSpin>
          </div>
        </aside>
      </div>
    </section>
  </div>
</template>

<style scoped>
.sector-workspace {
  display: grid;
  height: 100%;
  min-height: 0;
  gap: 6px;
  grid-template-columns: 240px minmax(0, 1fr);
}

.sector-sidebar {
  display: flex;
  min-height: 0;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
}

.sector-sidebar-head {
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
}

.sector-sidebar-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.sector-list-spin {
  height: 100%;
}

:deep(.sector-list-spin .n-spin-container) {
  height: 100%;
}

:deep(.sector-list-spin .n-spin-content) {
  height: 100%;
}

.sector-list {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 4px;
}

.sector-main {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 6px;
}

.chart-skeleton {
  flex: 1;
  min-height: 0;
  border: none;
  box-shadow: none;
  border-radius: 8px;
}

.sector-item {
  display: flex;
  width: 100%;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  border: none;
  border-radius: 8px;
  background: transparent;
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
  color: var(--text);
  transition: background-color 0.15s ease;
}

.sector-item:hover {
  background: color-mix(in srgb, var(--accent) 8%, var(--panel));
}

.sector-item.active {
  background: color-mix(in srgb, var(--accent) 14%, var(--panel));
  color: var(--accent);
}

.chart-members-row {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: minmax(0, 3fr) minmax(220px, 1fr);
  align-items: stretch;
  overflow: hidden;
}

.chart-pane {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  padding: 10px 12px;
  border-right: 1px solid var(--border);
}

.chart-toolbar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
  min-height: 28px;
}

.chart-title {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.chart-body,
.chart-spin {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

:deep(.chart-spin .n-spin-container) {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

:deep(.chart-spin .n-spin-content) {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.chart-canvas {
  flex: 1;
  min-height: 240px;
}

.chart-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
}

.members-pane {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  padding: 10px;
  overflow: hidden;
}

.members-head {
  flex-shrink: 0;
  margin-bottom: 6px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
}

.members-body,
.members-spin {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

:deep(.members-spin .n-spin-container) {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

:deep(.members-spin .n-spin-content) {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.members-table {
  flex: 1;
  min-height: 200px;
}

:deep(.members-table .n-data-table-th) {
  font-size: 11px;
  font-weight: 600;
  padding: 6px 8px;
}

:deep(.members-table .n-data-table-td) {
  padding: 6px 8px;
}

:deep(.members-table .money-cell) {
  display: inline-block;
  white-space: nowrap;
}

@media (max-width: 1024px) {
  .sector-workspace {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .sector-sidebar {
    max-height: 220px;
  }

  .chart-members-row {
    grid-template-columns: 1fr;
    min-height: 480px;
  }

  .chart-pane {
    border-right: none;
    border-bottom: 1px solid var(--border);
    min-height: 320px;
  }

  .members-pane {
    min-height: 240px;
  }
}
</style>
