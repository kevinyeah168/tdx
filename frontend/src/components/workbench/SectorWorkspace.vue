<script setup lang="ts">
import {
  NButton,
  NDataTable,
  NDropdown,
  NEmpty,
  NInput,
  NModal,
  NSpin,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h, onMounted, onUnmounted, ref } from 'vue'

import { CATALOG_REFRESH_MS } from '@/constants/refresh'

import MemberListDrawer, { type MemberListKind } from '@/components/workbench/MemberListDrawer.vue'
import MemberStockFlowModal from '@/components/workbench/MemberStockFlowModal.vue'
import SectorFundChart from '@/components/workbench/SectorFundChart.vue'
import SectorHeader, { type StatKind } from '@/components/workbench/SectorHeader.vue'
import SessionSkeleton from '@/components/workbench/SessionSkeleton.vue'
import { useSectorStore, type SectorTypeFilter } from '@/stores/sectorStore'
import { fmtMoneyCompact, fmtNetRatio, fmtPct, chgTone, toneClass } from '@/utils/format'
import { todayTradeDate } from '@/utils/tradeDate'
import type { SectorMemberRankItem } from '@/api/sectors'

const emit = defineEmits<{
  openSettings: []
}>()

const sectorStore = useSectorStore()
const {
  selected,
  filteredItems,
  importedFilteredItems,
  fundFlow,
  memberRanks,
  breadth,
  fundLoading,
  membersLoading,
  latestMainFlow,
  hasSessionData,
  groups,
  activeGroup,
} = storeToRefs(sectorStore)

const drawerOpen = ref(false)
const drawerKind = ref<MemberListKind | null>(null)
const memberFlowOpen = ref(false)
const memberFlowTarget = ref<SectorMemberRankItem | null>(null)
const quickCreateOpen = ref(false)
const newGroupName = ref('')
const creatingGroup = ref(false)

const chartTitle = computed(() => {
  if (!selected.value) return '明盘净额分时'
  return `${selected.value.name} · 明盘净额`
})

const isCustomGroup = computed(() => sectorStore.activeGroupId !== 'all')

const sidebarSections = computed(() => {
  const sections: Array<{ key: string; title: string; items: typeof filteredItems.value }> = []
  if (importedFilteredItems.value.length) {
    sections.push({
      key: 'imported',
      title: `导入板块 (${importedFilteredItems.value.length})`,
      items: importedFilteredItems.value,
    })
  }
  if (filteredItems.value.length) {
    const title = isCustomGroup.value
      ? `${activeGroup.value?.name ?? '分组'} (${filteredItems.value.length})`
      : `板块 (${filteredItems.value.length})`
    sections.push({
      key: 'main',
      title,
      items: filteredItems.value,
    })
  }
  return sections
})

let importedCatalogTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  importedCatalogTimer = window.setInterval(() => {
    void sectorStore.refreshImportedSectorsIfChanged()
  }, CATALOG_REFRESH_MS)
})

onUnmounted(() => {
  if (importedCatalogTimer != null) {
    window.clearInterval(importedCatalogTimer)
    importedCatalogTimer = null
  }
})

const groupDropdownOptions = computed(() =>
  groups.value.map((group) => ({
    key: group.id,
    label: group.name,
  })),
)

function openMemberList(kind: StatKind) {
  drawerKind.value = kind
  drawerOpen.value = true
}

const typeTabs: { key: SectorTypeFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'industry', label: '行业' },
  { key: 'concept', label: '概念' },
]

function renderMemberMetric(
  value: number | null | undefined,
  opts?: { bold?: boolean; pct?: boolean; ratio?: boolean },
) {
  const text = opts?.pct ? fmtPct(value) : opts?.ratio ? fmtNetRatio(value) : fmtMoneyCompact(value)
  return h(
    'span',
    {
      class: [
        'num money-cell whitespace-nowrap text-[10px]',
        opts?.bold ? 'font-600' : '',
        toneClass(chgTone(value)),
      ].join(' '),
    },
    text,
  )
}

const memberColumns = [
  {
    title: '个股',
    key: 'name',
    width: 68,
    ellipsis: { tooltip: true },
    render: (row: SectorMemberRankItem) =>
      h(
        'div',
        {
          class: 'member-row-name member-row-link truncate text-[11px] font-500',
          title: `${row.name} ${row.symbol}`,
        },
        row.name,
      ),
  },
  {
    title: '明盘',
    key: 'main_cumulative',
    width: 64,
    align: 'right' as const,
    className: 'member-col-main',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) =>
      Number(a.main_cumulative || 0) - Number(b.main_cumulative || 0),
    defaultSortOrder: 'descend' as const,
    render: (row: SectorMemberRankItem) => renderMemberMetric(row.main_cumulative, { bold: true }),
  },
  {
    title: '暗盘',
    key: 'gray_cumulative',
    width: 64,
    align: 'right' as const,
    className: 'member-col-gray',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) => {
      const av = a.gray_cumulative
      const bv = b.gray_cumulative
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render: (row: SectorMemberRankItem) => renderMemberMetric(row.gray_cumulative, { bold: true }),
  },
  {
    title: '净比',
    key: 'main_net_ratio',
    width: 44,
    align: 'right' as const,
    className: 'member-col-ratio',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) => {
      const av = a.main_net_ratio
      const bv = b.main_net_ratio
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render: (row: SectorMemberRankItem) => renderMemberMetric(row.main_net_ratio, { ratio: true }),
  },
  {
    title: '占比',
    key: 'main_amount_ratio',
    width: 44,
    align: 'right' as const,
    className: 'member-col-ratio',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) => {
      const av = a.main_amount_ratio
      const bv = b.main_amount_ratio
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render: (row: SectorMemberRankItem) =>
      renderMemberMetric(row.main_amount_ratio, { ratio: true }),
  },
  {
    title: '涨幅',
    key: 'change_pct',
    width: 50,
    align: 'right' as const,
    className: 'member-col-change',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) =>
      Number(a.change_pct || 0) - Number(b.change_pct || 0),
    render: (row: SectorMemberRankItem) => renderMemberMetric(row.change_pct, { pct: true }),
  },
]

const headerTime = computed(() => {
  const date = sectorStore.tradeDate.replace(/-/g, '/')
  if (!hasSessionData.value) return date
  const minute = fundFlow.value?.latest_complete_minute || sectorStore.replayMinute
  return `${date} ${minute}`
})

const memberReplayMinute = computed(
  () => fundFlow.value?.latest_complete_minute || sectorStore.replayMinute,
)

function openMemberFlow(row: SectorMemberRankItem) {
  memberFlowTarget.value = row
  memberFlowOpen.value = true
}

async function createGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  creatingGroup.value = true
  try {
    await sectorStore.createGroup(name)
    newGroupName.value = ''
    quickCreateOpen.value = false
  } finally {
    creatingGroup.value = false
  }
}

function addSelectedToGroup(groupId: string) {
  if (!selected.value) return
  void sectorStore.addSectorToGroup(groupId, selected.value.sector_id)
}

function removeFromActiveGroup(sectorId: string) {
  if (!activeGroup.value) return
  void sectorStore.removeSectorFromGroup(activeGroup.value.id, sectorId)
}
</script>

<template>
  <div class="sector-workspace">
    <aside class="panel-card sector-sidebar">
      <div class="sector-sidebar-head">
        <div class="sidebar-title-row">
          <p class="m-0 text-sm font-600">板块列表</p>
          <NButton size="tiny" quaternary @click="emit('openSettings')">管理分组</NButton>
        </div>

        <div class="group-tabs">
          <button
            type="button"
            class="group-tab"
            :class="{ active: sectorStore.activeGroupId === 'all' }"
            @click="void sectorStore.setActiveGroup('all')"
          >
            全部
          </button>
          <button
            v-for="group in groups"
            :key="group.id"
            type="button"
            class="group-tab"
            :class="{ active: sectorStore.activeGroupId === group.id }"
            @click="void sectorStore.setActiveGroup(group.id)"
          >
            {{ group.name }}
            <span class="group-count">{{ group.sector_ids.length }}</span>
          </button>
          <button type="button" class="group-tab group-tab-add" title="新建分组" @click="quickCreateOpen = true">
            +
          </button>
        </div>

        <div v-if="!isCustomGroup" class="mt-2 flex flex-wrap gap-1">
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
          :placeholder="isCustomGroup ? '在当前分组内搜索' : '搜索板块名称或代码'"
          clearable
        />

        <p v-if="isCustomGroup" class="group-hint">
          在设置页搜索添加板块；此处可切换分组并查看列表。
        </p>
      </div>

      <div class="sector-sidebar-body">
        <NSpin :show="sectorStore.loading" class="sector-list-spin">
          <div class="sector-list">
            <template v-for="section in sidebarSections" :key="section.key">
              <div class="sector-list-section-head">
                <span class="sector-list-section-title">{{ section.title }}</span>
              </div>
              <div
                v-for="sector in section.items"
                :key="`${section.key}-${sector.sector_id}`"
                class="sector-item-wrap"
              >
                <button
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
                <button
                  v-if="isCustomGroup && section.key === 'main'"
                  type="button"
                  class="sector-remove"
                  title="从分组移除"
                  @click.stop="removeFromActiveGroup(sector.sector_id)"
                >
                  ×
                </button>
                <NDropdown
                  v-else-if="groups.length && sector.sector_id === sectorStore.selectedId"
                  trigger="click"
                  :options="groupDropdownOptions"
                  @select="addSelectedToGroup"
                >
                  <button type="button" class="sector-add-group" title="加入分组">+</button>
                </NDropdown>
              </div>
            </template>
            <NEmpty
              v-if="!sidebarSections.length"
              class="py-8"
              :description="isCustomGroup ? '分组为空，请搜索添加板块' : '无匹配板块'"
              size="small"
            />
          </div>
        </NSpin>
      </div>
    </aside>

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
        v-model:kind="drawerKind"
        :sector-name="selected?.name ?? ''"
        :breadth="breadth"
        @open-member-flow="openMemberFlow"
      />

      <MemberStockFlowModal
        v-model:show="memberFlowOpen"
        :symbol="memberFlowTarget?.symbol ?? ''"
        :name="memberFlowTarget?.name ?? ''"
        :trade-date="sectorStore.tradeDate"
        :replay-minute="memberReplayMinute"
        :change-pct="memberFlowTarget?.change_pct"
        :cum-main="memberFlowTarget?.main_cumulative"
        :cum-gray="memberFlowTarget?.gray_cumulative"
      />

      <div v-if="selected" class="chart-members-row panel-card">
        <div class="chart-pane">
          <div class="chart-toolbar">
            <span class="chart-title">{{ chartTitle }}</span>
          </div>

          <SessionSkeleton
            v-if="!hasSessionData"
            class="chart-skeleton"
            :trade-date="sectorStore.tradeDate"
            :title="sectorStore.tradeDate === todayTradeDate() ? '今日尚未开盘' : '该交易日暂无数据'"
          />

          <div v-else class="chart-body">
            <NSpin :show="fundLoading" class="chart-spin">
              <SectorFundChart
                v-if="fundFlow?.points.length"
                :payload="fundFlow"
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
              点击表头排序 · 共 {{ memberRanks.length || selected?.member_count || 0 }} 只
            </p>
          </div>
          <div class="members-body">
            <NSpin :show="membersLoading && hasSessionData" class="members-spin">
              <NDataTable
                v-if="memberRanks.length"
                :key="sectorStore.selectedId"
                :columns="memberColumns"
                :data="memberRanks"
                :bordered="false"
                size="small"
                flex-height
                :single-line="false"
                class="members-table"
                :row-props="(row) => ({ style: 'cursor: pointer', onClick: () => openMemberFlow(row) })"
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

    <NModal v-model:show="quickCreateOpen" preset="card" title="新建分组" style="width: 380px">
      <div class="manage-block">
        <p class="hint">分组保存在 Workbench 元数据库。完整管理（增删板块、重命名）请前往设置页。</p>
        <div class="manage-row">
          <NInput v-model:value="newGroupName" placeholder="新分组名称" @keyup.enter="createGroup" />
          <NButton type="primary" :loading="creatingGroup" @click="createGroup">创建</NButton>
        </div>
        <NButton quaternary size="small" @click="emit('openSettings')">打开设置 · 板块分组</NButton>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.sector-workspace {
  display: grid;
  height: 100%;
  min-height: 0;
  gap: 6px;
  grid-template-columns: 260px minmax(0, 1fr);
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

.group-hint {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.sector-sidebar-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.sector-list-spin {
  height: 100%;
}

:deep(.sector-list-spin .n-spin-container),
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

.sector-list-section-head {
  position: sticky;
  top: 0;
  z-index: 1;
  margin: 2px 0 4px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 92%, var(--bg));
}

.sector-list-section-head:not(:first-child) {
  margin-top: 8px;
}

.sector-list-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
}

.sector-item-wrap {
  display: flex;
  align-items: stretch;
  gap: 2px;
}

.sector-main {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 6px;
}

.sector-item {
  display: flex;
  flex: 1;
  min-width: 0;
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

.sector-item:hover,
.sector-item.active {
  background: color-mix(in srgb, var(--accent) 14%, var(--panel));
  color: var(--accent);
}

.sector-remove,
.sector-add-group {
  flex-shrink: 0;
  width: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.sector-remove:hover,
.sector-add-group:hover {
  background: color-mix(in srgb, var(--accent) 10%, var(--panel));
  color: var(--accent);
}

.chart-members-row {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: minmax(0, 3fr) minmax(340px, 1.1fr);
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
  flex-shrink: 0;
  margin-bottom: 6px;
  min-height: 24px;
}

.chart-title {
  font-size: 14px;
  font-weight: 600;
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

:deep(.members-spin .n-spin-container),
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

:deep(.members-table .n-data-table-table) {
  table-layout: fixed;
  width: 100%;
}

:deep(.members-table .n-data-table-th),
:deep(.members-table .n-data-table-td) {
  padding: 5px 3px !important;
  font-size: 10px;
  white-space: nowrap;
}

:deep(.members-table .n-data-table-th) {
  font-weight: 600;
}

:deep(.members-table .n-data-table-th__title-wrapper),
:deep(.members-table .n-data-table-th__title),
:deep(.members-table .n-data-table-sorter) {
  white-space: nowrap !important;
  flex-wrap: nowrap !important;
}

:deep(.members-table .n-data-table-th:first-child),
:deep(.members-table .n-data-table-td:first-child) {
  padding-right: 10px !important;
}

:deep(.members-table .member-col-main) {
  padding-left: 8px !important;
  padding-right: 14px !important;
}

:deep(.members-table .member-col-gray) {
  padding-left: 8px !important;
  padding-right: 14px !important;
}

:deep(.members-table .member-col-ratio) {
  padding-left: 6px !important;
  padding-right: 12px !important;
}

:deep(.members-table .member-col-change) {
  padding-left: 6px !important;
  padding-right: 8px !important;
}

:deep(.member-row-name) {
  min-width: 0;
  line-height: 1.25;
}

:deep(.member-row-link) {
  color: var(--primary);
}

:deep(.members-table .n-data-table-tr:hover) .member-row-link {
  text-decoration: underline;
}

.manage-block {
  display: grid;
  gap: 12px;
}

.manage-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}

@media (max-width: 1024px) {
  .sector-workspace {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .sector-sidebar {
    max-height: 280px;
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
}
</style>
