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
import { computed, h, ref } from 'vue'

import MemberListDrawer, { type MemberListKind } from '@/components/workbench/MemberListDrawer.vue'
import SectorFundChart from '@/components/workbench/SectorFundChart.vue'
import SectorHeader, { type StatKind } from '@/components/workbench/SectorHeader.vue'
import SessionSkeleton from '@/components/workbench/SessionSkeleton.vue'
import { useSectorStore, type SectorTypeFilter } from '@/stores/sectorStore'
import { fmtMoneyCompact, fmtPct, chgTone, toneClass } from '@/utils/format'
import { todayTradeDate } from '@/utils/tradeDate'
import type { SectorMemberRankItem } from '@/api/sectors'

const emit = defineEmits<{
  openStock: [symbol: string]
  openSettings: []
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
  groups,
  activeGroup,
} = storeToRefs(sectorStore)

const drawerOpen = ref(false)
const drawerKind = ref<MemberListKind | null>(null)
const quickCreateOpen = ref(false)
const newGroupName = ref('')
const creatingGroup = ref(false)

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

const chartTitle = computed(() => {
  if (!selected.value) return '主力净额分时'
  return `${selected.value.name} · 主力净额`
})

const isCustomGroup = computed(() => sectorStore.activeGroupId !== 'all')

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
            <div
              v-for="sector in filteredItems"
              :key="sector.sector_id"
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
                v-if="isCustomGroup"
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
            <NEmpty
              v-if="!filteredItems.length"
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
        :kind="drawerKind"
        :title="`${selected?.name ?? ''} · ${drawerTitle}`"
        :items="drawerItems"
        @open-stock="emit('openStock', $event)"
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
  grid-template-columns: minmax(0, 3fr) minmax(220px, 1fr);
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
