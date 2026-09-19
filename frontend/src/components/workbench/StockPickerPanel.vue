<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import { NButton, NCheckbox, NDataTable, NInput } from 'naive-ui'
import { computed, h, ref, watch } from 'vue'

import { apiGet } from '@/api/client'
import type { SearchResponse } from '@/types/api'

const props = withDefaults(
  defineProps<{
    excludedSymbols: string[]
    embedded?: boolean
    tableMaxHeight?: number
  }>(),
  {
    embedded: false,
    tableMaxHeight: 280,
  },
)

const emit = defineEmits<{
  add: [symbols: string[]]
}>()

type StockHit = { symbol: string; name: string }

const loading = ref(false)
const search = ref('')
const hits = ref<StockHit[]>([])
const selectedSymbols = ref<Set<string>>(new Set())
const adding = ref(false)

const excludedSet = computed(() => new Set(props.excludedSymbols.map((s) => s.toUpperCase())))

const columns = computed(() => [
  {
    title: '',
    key: 'pick',
    width: 36,
    render: (row: StockHit) =>
      h(NCheckbox, {
        size: 'small',
        checked: selectedSymbols.value.has(row.symbol),
        onUpdateChecked: (checked: boolean) => togglePick(row.symbol, checked),
      }),
  },
  { title: '个股', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '代码',
    key: 'symbol',
    width: 96,
    render: (row: StockHit) =>
      h('span', { class: 'num text-[11px] text-[var(--muted)]' }, row.symbol),
  },
])

const runSearch = useDebounceFn(async (query: string) => {
  const trimmed = query.trim()
  if (!trimmed) {
    hits.value = []
    return
  }
  loading.value = true
  try {
    const response = await apiGet<SearchResponse>('/api/v1/market/search', { q: trimmed })
    hits.value = response.results
      .filter((item) => !excludedSet.value.has(item.symbol.toUpperCase()))
      .map((item) => ({ symbol: item.symbol.toUpperCase(), name: item.name }))
  } catch {
    hits.value = []
  } finally {
    loading.value = false
  }
}, 250)

function onSearchInput(value: string) {
  search.value = value
  clearSelection()
  void runSearch(value)
}

function togglePick(symbol: string, checked: boolean) {
  const next = new Set(selectedSymbols.value)
  if (checked) next.add(symbol)
  else next.delete(symbol)
  selectedSymbols.value = next
}

function selectAllVisible() {
  selectedSymbols.value = new Set(hits.value.map((row) => row.symbol))
}

function clearSelection() {
  selectedSymbols.value = new Set()
}

function confirmAdd() {
  if (!selectedSymbols.value.size) return
  adding.value = true
  try {
    emit('add', [...selectedSymbols.value])
    clearSelection()
  } finally {
    adding.value = false
  }
}

watch(
  () => props.excludedSymbols,
  () => {
    if (search.value.trim()) {
      void runSearch(search.value)
    }
  },
)
</script>

<template>
  <div class="picker-panel" :class="{ 'picker-panel--embedded': embedded }">
    <div class="picker-toolbar">
      <NInput
        :value="search"
        class="search-input"
        size="small"
        placeholder="搜索个股名称或代码"
        clearable
        @update:value="onSearchInput"
      />
      <span class="picker-meta">
        <template v-if="loading">搜索中…</template>
        <template v-else-if="search.trim() && hits.length">{{ hits.length }} 条 · 已选 {{ selectedSymbols.size }}</template>
        <template v-else-if="search.trim()">无匹配</template>
        <template v-else>输入关键词搜索</template>
      </span>
    </div>
    <div v-if="search.trim()" class="picker-actions">
      <NButton size="tiny" quaternary :disabled="!hits.length" @click="selectAllVisible">
        全选当前
      </NButton>
      <NButton size="tiny" quaternary :disabled="!selectedSymbols.size" @click="clearSelection">
        清空
      </NButton>
      <NButton
        size="small"
        type="primary"
        :disabled="!selectedSymbols.size"
        :loading="adding"
        @click="confirmAdd"
      >
        添加选中{{ selectedSymbols.size ? ` (${selectedSymbols.size})` : '' }}
      </NButton>
    </div>
    <NDataTable
      v-if="search.trim()"
      size="small"
      :bordered="false"
      :columns="columns"
      :data="hits"
      :loading="loading"
      :max-height="tableMaxHeight"
      virtual-scroll
    />
    <p v-else-if="embedded && !search.trim()" class="picker-hint">输入关键词搜索个股。</p>
  </div>
</template>

<style scoped>
.picker-panel {
  display: grid;
  gap: 8px;
}

.picker-panel--embedded {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.picker-hint {
  margin: auto 0 0;
  font-size: 11px;
  color: var(--muted);
  text-align: center;
}

.picker-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.search-input {
  flex: 1;
  min-width: 160px;
}

.picker-meta {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.picker-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}
</style>
