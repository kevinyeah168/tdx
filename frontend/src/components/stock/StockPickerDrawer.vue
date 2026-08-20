<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import {
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NInput,
  NSpace,
  NTag,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h, watch } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import type { BoardItem } from '@/types/board'
import { chgTone, fmtPct, toneClass } from '@/utils/format'

const boardStore = useBoardStore()
const {
  stockPickerOpen,
  stockPickerQuery,
  stockPickerCatalog,
  stockPickerSelected,
  stockPickerSaving,
} = storeToRefs(boardStore)

const debouncedSearch = useDebounceFn(() => {
  boardStore.loadStockCatalog()
}, 250)

watch(stockPickerQuery, () => {
  debouncedSearch()
})

const columns = computed(() => [
  {
    title: '',
    key: 'picked',
    width: 40,
    render(row: BoardItem) {
      const on = boardStore.isStockPicked(row.id)
      return h(
        'span',
        {
          class: `inline-flex h-4.5 w-4.5 items-center justify-center rounded border text-xs ${
            on
              ? 'border-[var(--accent)] text-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_10%,transparent)]'
              : 'border-[var(--border)] text-transparent'
          }`,
        },
        on ? '✓' : '',
      )
    },
  },
  {
    title: '名称',
    key: 'name',
    ellipsis: { tooltip: true },
  },
  {
    title: '代码',
    key: 'id',
    width: 96,
    render(row: BoardItem) {
      return h('span', { class: 'num text-xs text-[var(--muted)]' }, row.id)
    },
  },
  {
    title: '涨跌',
    key: 'change_pct',
    width: 72,
    render(row: BoardItem) {
      return h(
        'span',
        { class: `num text-xs ${toneClass(chgTone(row.change_pct))}` },
        fmtPct(row.change_pct),
      )
    },
  },
])

function rowProps(row: BoardItem) {
  return {
    style: { cursor: 'pointer' },
    onClick: () => boardStore.toggleStockPick(row),
  }
}
</script>

<template>
  <NDrawer
    :show="stockPickerOpen"
    :width="480"
    placement="right"
    @update:show="(v) => !v && boardStore.closeStockPicker()"
  >
    <NDrawerContent title="自选个股" closable>
      <NSpace vertical :size="12">
        <NInput
          v-model:value="stockPickerQuery"
          clearable
          placeholder="搜索名称或代码，如 600519、茅台"
        />

        <div v-if="stockPickerSelected.length" class="flex flex-wrap items-center gap-2">
          <span class="text-xs text-[var(--muted)]">
            已选 {{ stockPickerSelected.length }}
          </span>
          <NTag
            v-for="s in stockPickerSelected"
            :key="s.id"
            closable
            size="small"
            type="info"
            @close="boardStore.toggleStockPick(s)"
          >
            {{ s.name }} · {{ s.id }}
          </NTag>
        </div>

        <NDataTable
          :columns="columns"
          :data="stockPickerCatalog"
          :bordered="false"
          size="small"
          max-height="52vh"
          :row-props="rowProps"
        />
      </NSpace>

      <template #footer>
        <div class="flex w-full items-center justify-between gap-3">
          <NButton size="small" @click="boardStore.clearStockPicker">
            清空自选
          </NButton>
          <NButton
            type="primary"
            size="small"
            :loading="stockPickerSaving"
            @click="boardStore.saveStockPicker"
          >
            保存并刷新
          </NButton>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>
