<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import {
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NInput,
  NSelect,
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
  pickerOpen,
  pickerType,
  pickerQuery,
  pickerCatalog,
  pickerSelected,
  pickerSaving,
} = storeToRefs(boardStore)

const typeOptions = [
  { label: '行业', value: 'HY' },
  { label: '概念', value: 'GN' },
  { label: '二级行业', value: 'HY2' },
]

const debouncedSearch = useDebounceFn(() => {
  boardStore.loadCatalog()
}, 250)

watch(pickerType, () => {
  boardStore.loadCatalog()
})

watch(pickerQuery, () => {
  debouncedSearch()
})

const columns = computed(() => [
  {
    title: '',
    key: 'picked',
    width: 40,
    render(row: BoardItem) {
      const on = boardStore.isPicked(row.id)
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
    width: 88,
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
    onClick: () => boardStore.togglePick(row),
  }
}
</script>

<template>
  <NDrawer
    :show="pickerOpen"
    :width="480"
    placement="right"
    @update:show="(v) => !v && boardStore.closePicker()"
  >
    <NDrawerContent title="自选板块" closable>
      <NSpace vertical :size="12">
        <NSpace :size="8" class="w-full">
          <NSelect
            v-model:value="pickerType"
            :options="typeOptions"
            style="width: 120px"
          />
          <NInput
            v-model:value="pickerQuery"
            clearable
            placeholder="搜索名称或代码，如 881338"
            class="flex-1"
          />
        </NSpace>

        <div v-if="pickerSelected.length" class="flex flex-wrap items-center gap-2">
          <span class="text-xs text-[var(--muted)]">
            已选 {{ pickerSelected.length }}
          </span>
          <NTag
            v-for="b in pickerSelected"
            :key="b.id"
            closable
            size="small"
            type="info"
            @close="boardStore.togglePick(b)"
          >
            {{ b.name }} · {{ b.id }}
          </NTag>
        </div>

        <NDataTable
          :columns="columns"
          :data="pickerCatalog"
          :bordered="false"
          size="small"
          max-height="52vh"
          :row-props="rowProps"
        />
      </NSpace>

      <template #footer>
        <div class="flex w-full items-center justify-between gap-3">
          <NButton size="small" @click="boardStore.clearPicker">
            清空自选（恢复自动榜）
          </NButton>
          <NButton
            type="primary"
            size="small"
            :loading="pickerSaving"
            @click="boardStore.savePicker"
          >
            保存并刷新
          </NButton>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>
