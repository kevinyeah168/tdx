<script setup lang="ts">
import { NDataTable, NDrawer, NDrawerContent, NEmpty } from 'naive-ui'
import { computed, h } from 'vue'

import type { SectorMemberRankItem } from '@/api/sectors'
import { chgTone, fmtMoney, fmtPct, toneClass } from '@/utils/format'

export type MemberListKind = 'limit_up' | 'limit_down' | 'up' | 'down'

const show = defineModel<boolean>('show', { required: true })

defineProps<{
  kind: MemberListKind | null
  title: string
  items: SectorMemberRankItem[]
}>()

const emit = defineEmits<{
  openStock: [symbol: string]
}>()

const columns = computed(() => [
  {
    title: '个股',
    key: 'name',
    ellipsis: { tooltip: true },
    render: (row: SectorMemberRankItem) =>
      h('div', { class: 'min-w-0' }, [
        h('div', { class: 'truncate text-sm font-500' }, row.name),
        h('div', { class: 'num text-[11px] text-[var(--muted)]' }, row.symbol),
      ]),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    width: 88,
    render: (row: SectorMemberRankItem) =>
      h('span', { class: `num font-600 ${toneClass(chgTone(row.change_pct))}` }, fmtPct(row.change_pct)),
  },
  {
    title: '主力累计',
    key: 'main_cumulative',
    width: 100,
    render: (row: SectorMemberRankItem) =>
      h('span', { class: `num text-xs ${toneClass(chgTone(row.main_cumulative))}` }, fmtMoney(row.main_cumulative)),
  },
])
</script>

<template>
  <NDrawer v-model:show="show" :width="420" placement="right">
    <NDrawerContent :title="title" closable>
      <p class="mt-0 text-xs text-[var(--muted)]">共 {{ items.length }} 只 · 点击行查看个股详情</p>
      <NDataTable
        v-if="items.length"
        class="mt-3"
        :columns="columns"
        :data="items"
        :bordered="false"
        size="small"
        :max-height="520"
        :row-props="(row) => ({ style: 'cursor: pointer', onClick: () => emit('openStock', row.symbol) })"
      />
      <NEmpty v-else class="py-12" description="暂无个股" />
    </NDrawerContent>
  </NDrawer>
</template>
