<script setup lang="ts">
import { NDataTable, NDrawer, NDrawerContent, NEmpty } from 'naive-ui'
import { computed, h } from 'vue'

import type { SectorBreadthResponse, SectorMemberRankItem } from '@/api/sectors'
import { chgTone, fmtMoneyCompact, fmtNetRatio, fmtPct, toneClass } from '@/utils/format'

export type MemberListKind = 'limit_up' | 'limit_down' | 'up' | 'down'

const TAB_DEFS: { key: MemberListKind; label: string; tone: string }[] = [
  { key: 'limit_up', label: '涨停', tone: 'tone-limit-up' },
  { key: 'limit_down', label: '跌停', tone: 'tone-limit-down' },
  { key: 'up', label: '上涨', tone: 'tone-up' },
  { key: 'down', label: '下跌', tone: 'tone-down' },
]

const show = defineModel<boolean>('show', { required: true })
const kind = defineModel<MemberListKind | null>('kind', { required: true })

const props = defineProps<{
  sectorName: string
  breadth: SectorBreadthResponse | null
}>()

const emit = defineEmits<{
  openMemberFlow: [row: SectorMemberRankItem]
}>()

const activeTab = computed({
  get: () => kind.value ?? 'limit_up',
  set: (value: MemberListKind) => {
    kind.value = value
  },
})

const drawerTitle = computed(() => `${props.sectorName} · 涨跌统计`)

const currentItems = computed((): SectorMemberRankItem[] => {
  if (!props.breadth || !kind.value) return []
  return props.breadth[kind.value] ?? []
})

function tabCount(key: MemberListKind): number {
  return props.breadth?.counts?.[key] ?? props.breadth?.[key]?.length ?? 0
}

function renderMetric(
  value: number | null | undefined,
  opts?: { bold?: boolean; pct?: boolean; ratio?: boolean },
) {
  const text = opts?.pct ? fmtPct(value) : opts?.ratio ? fmtNetRatio(value) : fmtMoneyCompact(value)
  return h(
    'span',
    {
      class: [
        'num whitespace-nowrap text-xs',
        opts?.bold ? 'font-600' : '',
        toneClass(chgTone(value)),
      ].join(' '),
    },
    text,
  )
}

const columns = computed(() => [
  {
    title: '个股',
    key: 'name',
    width: 108,
    render: (row: SectorMemberRankItem) =>
      h(
        'div',
        { class: 'drawer-row-name truncate text-sm font-500', title: `${row.name} ${row.symbol}` },
        row.name,
      ),
  },
  {
    title: '明盘',
    key: 'main_cumulative',
    width: 88,
    align: 'right' as const,
    className: 'drawer-col-main',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) =>
      Number(a.main_cumulative || 0) - Number(b.main_cumulative || 0),
    render: (row: SectorMemberRankItem) => renderMetric(row.main_cumulative, { bold: true }),
  },
  {
    title: '暗盘',
    key: 'gray_cumulative',
    width: 88,
    align: 'right' as const,
    className: 'drawer-col-gray',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) => {
      const av = a.gray_cumulative
      const bv = b.gray_cumulative
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render: (row: SectorMemberRankItem) => renderMetric(row.gray_cumulative, { bold: true }),
  },
  {
    title: '净比',
    key: 'main_net_ratio',
    width: 64,
    align: 'right' as const,
    className: 'drawer-col-ratio',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) => {
      const av = a.main_net_ratio
      const bv = b.main_net_ratio
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render: (row: SectorMemberRankItem) => renderMetric(row.main_net_ratio, { ratio: true }),
  },
  {
    title: '占比',
    key: 'main_amount_ratio',
    width: 64,
    align: 'right' as const,
    className: 'drawer-col-ratio',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) => {
      const av = a.main_amount_ratio
      const bv = b.main_amount_ratio
      if (av == null && bv == null) return 0
      if (av == null) return -1
      if (bv == null) return 1
      return av - bv
    },
    render: (row: SectorMemberRankItem) => renderMetric(row.main_amount_ratio, { ratio: true }),
  },
  {
    title: '涨幅',
    key: 'change_pct',
    width: 72,
    align: 'right' as const,
    className: 'drawer-col-change',
    sorter: (a: SectorMemberRankItem, b: SectorMemberRankItem) =>
      Number(a.change_pct || 0) - Number(b.change_pct || 0),
    defaultSortOrder: 'descend' as const,
    render: (row: SectorMemberRankItem) => renderMetric(row.change_pct, { pct: true }),
  },
])
</script>

<template>
  <NDrawer v-model:show="show" :width="600" placement="right">
    <NDrawerContent :title="drawerTitle" closable class="member-drawer-content">
      <div class="member-drawer-tabs" role="tablist" aria-label="涨跌分类">
        <button
          v-for="tab in TAB_DEFS"
          :key="tab.key"
          type="button"
          role="tab"
          class="member-tab"
          :class="[tab.tone, { active: activeTab === tab.key }]"
          :aria-selected="activeTab === tab.key"
          @click="activeTab = tab.key"
        >
          <span>{{ tab.label }}</span>
          <span class="member-tab-count">{{ tabCount(tab.key) }}</span>
        </button>
      </div>

      <p class="member-drawer-hint">共 {{ currentItems.length }} 只 · 点击行查看个股详情</p>

      <div class="member-drawer-table-wrap">
        <NDataTable
          v-if="currentItems.length"
          :key="activeTab"
          flex-height
          class="member-drawer-table"
          :columns="columns"
          :data="currentItems"
          :bordered="false"
          size="small"
          :single-line="true"
          :row-props="(row) => ({ style: 'cursor: pointer', onClick: () => emit('openMemberFlow', row) })"
        />
        <NEmpty v-else class="member-drawer-empty" description="该分类暂无个股" />
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.member-drawer-content :deep(.n-drawer-body-content-wrapper) {
  display: flex;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
}

.member-drawer-tabs {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 8px;
}

.member-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--panel) 94%, var(--bg));
  padding: 6px 12px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
  transition: border-color 0.12s ease, background-color 0.12s ease, color 0.12s ease;
}

.member-tab-count {
  min-width: 1.25rem;
  font-size: 12px;
  font-weight: 700;
  text-align: right;
}

.member-tab.tone-limit-up .member-tab-count,
.member-tab.tone-up .member-tab-count {
  color: var(--up);
}

.member-tab.tone-limit-down .member-tab-count,
.member-tab.tone-down .member-tab-count {
  color: var(--down);
}

.member-tab.tone-limit-up:hover,
.member-tab.tone-up:hover {
  border-color: color-mix(in srgb, var(--up) 35%, var(--border));
  background: color-mix(in srgb, var(--up) 8%, var(--panel));
}

.member-tab.tone-limit-down:hover,
.member-tab.tone-down:hover {
  border-color: color-mix(in srgb, var(--down) 35%, var(--border));
  background: color-mix(in srgb, var(--down) 8%, var(--panel));
}

.member-tab.tone-limit-up.active {
  border-color: color-mix(in srgb, var(--up) 50%, var(--border));
  background: color-mix(in srgb, var(--up) 14%, var(--panel));
  color: var(--up);
}

.member-tab.tone-up.active {
  border-color: color-mix(in srgb, var(--up) 42%, var(--border));
  background: color-mix(in srgb, var(--up) 10%, var(--panel));
  color: var(--up);
}

.member-tab.tone-limit-down.active {
  border-color: color-mix(in srgb, var(--down) 50%, var(--border));
  background: color-mix(in srgb, var(--down) 14%, var(--panel));
  color: var(--down);
}

.member-tab.tone-down.active {
  border-color: color-mix(in srgb, var(--down) 42%, var(--border));
  background: color-mix(in srgb, var(--down) 10%, var(--panel));
  color: var(--down);
}

.member-drawer-hint {
  flex-shrink: 0;
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.member-drawer-table-wrap {
  display: flex;
  flex: 1;
  min-height: 0;
  margin-top: 8px;
  flex-direction: column;
}

.member-drawer-table {
  flex: 1;
  min-height: 320px;
}

.member-drawer-empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
}

:deep(.member-drawer-table .n-data-table-table) {
  table-layout: fixed;
  width: 100%;
}

:deep(.member-drawer-table .n-data-table-th),
:deep(.member-drawer-table .n-data-table-td) {
  padding: 6px 4px !important;
  white-space: nowrap;
}

:deep(.member-drawer-table .n-data-table-th) {
  font-weight: 600;
}

:deep(.member-drawer-table .n-data-table-th__title-wrapper),
:deep(.member-drawer-table .n-data-table-th__title),
:deep(.member-drawer-table .n-data-table-sorter) {
  white-space: nowrap !important;
  flex-wrap: nowrap !important;
}

:deep(.member-drawer-table .drawer-col-main) {
  padding-left: 10px !important;
  padding-right: 14px !important;
}

:deep(.member-drawer-table .drawer-col-gray) {
  padding-left: 8px !important;
  padding-right: 14px !important;
}

:deep(.member-drawer-table .drawer-col-ratio) {
  padding-left: 8px !important;
  padding-right: 12px !important;
}

:deep(.member-drawer-table .drawer-col-change) {
  padding-left: 8px !important;
  padding-right: 8px !important;
}

:deep(.drawer-row-name) {
  min-width: 0;
}
</style>
