<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import { NButton, NCheckbox, NDataTable, NInput, NSelect } from 'naive-ui'
import { computed, h, onMounted, ref, watch } from 'vue'

import { fetchSectors, searchSectors } from '@/api/sectors'
import { sectorTypeShort } from '@/utils/format'
import type { SectorSummary } from '@/types/api'

const props = withDefaults(
  defineProps<{
    excludedIds: string[]
    embedded?: boolean
    tableMaxHeight?: number
  }>(),
  {
    embedded: false,
    tableMaxHeight: 280,
  },
)

const emit = defineEmits<{
  add: [sectorIds: string[]]
}>()

type SectorTypeFilter =
  | 'all'
  | 'industry'
  | 'concept'
  | 'industry2'
  | 'classic_index'
  | 'style'
  | 'region'
  | 'custom'

const loading = ref(false)
const search = ref('')
const sectorTypeFilter = ref<SectorTypeFilter>('all')
const catalog = ref<SectorSummary[]>([])
const searchHits = ref<SectorSummary[]>([])
const selectedIds = ref<Set<string>>(new Set())
const adding = ref(false)

const typeFilterOptions = [
  { label: '全部类型', value: 'all' },
  { label: '行业', value: 'industry' },
  { label: '概念', value: 'concept' },
  { label: '二级行业', value: 'industry2' },
  { label: '板块指数', value: 'classic_index' },
  { label: '风格', value: 'style' },
  { label: '地域', value: 'region' },
  { label: '自定义', value: 'custom' },
]

const excludedSet = computed(() => new Set(props.excludedIds))

const browseRows = computed(() => {
  let items = catalog.value.filter((item) => !excludedSet.value.has(item.sector_id))
  if (sectorTypeFilter.value !== 'all') {
    items = items.filter((item) => item.sector_type === sectorTypeFilter.value)
  }
  return items
})

const displayRows = computed(() => {
  if (search.value.trim()) return searchHits.value
  return browseRows.value
})

const columns = computed(() => [
  {
    title: '',
    key: 'pick',
    width: 36,
    render: (row: SectorSummary) =>
      h(NCheckbox, {
        size: 'small',
        checked: selectedIds.value.has(row.sector_id),
        onUpdateChecked: (checked: boolean) => togglePick(row.sector_id, checked),
      }),
  },
  { title: '板块', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '类型',
    key: 'sector_type',
    width: 72,
    render: (row: SectorSummary) => sectorTypeShort(row.sector_type, row.sector_id),
  },
  {
    title: '代码',
    key: 'sector_id',
    width: 88,
    render: (row: SectorSummary) =>
      h('span', { class: 'num text-[11px] text-[var(--muted)]' }, row.sector_id),
  },
])

async function loadCatalog() {
  loading.value = true
  try {
    const response = await fetchSectors({ limit: 1500 })
    catalog.value = response.items
  } catch {
    catalog.value = []
  } finally {
    loading.value = false
  }
}

const runSearch = useDebounceFn(async (query: string) => {
  const trimmed = query.trim()
  if (!trimmed) {
    searchHits.value = []
    return
  }
  loading.value = true
  try {
    const response = await searchSectors(trimmed, 120)
    let items = response.items.filter((item) => !excludedSet.value.has(item.sector_id))
    if (sectorTypeFilter.value !== 'all') {
      items = items.filter((item) => item.sector_type === sectorTypeFilter.value)
    }
    searchHits.value = items
  } catch {
    searchHits.value = []
  } finally {
    loading.value = false
  }
}, 250)

function onSearchInput(value: string) {
  search.value = value
  clearSelection()
  void runSearch(value)
}

function onTypeChange() {
  clearSelection()
  if (search.value.trim()) {
    void runSearch(search.value)
  }
}

function togglePick(sectorId: string, checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) next.add(sectorId)
  else next.delete(sectorId)
  selectedIds.value = next
}

function selectAllVisible() {
  selectedIds.value = new Set(displayRows.value.map((row) => row.sector_id))
}

function clearSelection() {
  selectedIds.value = new Set()
}

function confirmAdd() {
  if (!selectedIds.value.size) return
  adding.value = true
  try {
    emit('add', [...selectedIds.value])
    clearSelection()
  } finally {
    adding.value = false
  }
}

watch(
  () => props.excludedIds,
  () => {
    if (search.value.trim()) {
      void runSearch(search.value)
    }
  },
)

onMounted(() => {
  void loadCatalog()
})

defineExpose({ reloadCatalog: loadCatalog })
</script>

<template>
  <div class="picker-panel" :class="{ 'picker-panel--embedded': embedded }">
    <div class="picker-toolbar">
      <NSelect
        v-model:value="sectorTypeFilter"
        class="type-filter"
        size="small"
        :options="typeFilterOptions"
        @update:value="onTypeChange"
      />
      <NInput
        :value="search"
        class="search-input"
        size="small"
        placeholder="搜索板块名称或代码"
        clearable
        @update:value="onSearchInput"
      />
      <span class="picker-meta">
        <template v-if="loading">加载中…</template>
        <template v-else>{{ displayRows.length }} 条 · 已选 {{ selectedIds.size }}</template>
      </span>
    </div>
    <div class="picker-actions">
      <NButton size="tiny" quaternary :disabled="!displayRows.length" @click="selectAllVisible">
        全选当前
      </NButton>
      <NButton size="tiny" quaternary :disabled="!selectedIds.size" @click="clearSelection">
        清空
      </NButton>
      <NButton
        size="small"
        type="primary"
        :disabled="!selectedIds.size"
        :loading="adding"
        @click="confirmAdd"
      >
        添加选中{{ selectedIds.size ? ` (${selectedIds.size})` : '' }}
      </NButton>
    </div>
    <NDataTable
      size="small"
      :bordered="false"
      :columns="columns"
      :data="displayRows"
      :loading="loading"
      :max-height="tableMaxHeight"
      virtual-scroll
    />
    <p v-if="!search.trim()" class="picker-hint">按类型浏览全部板块，或直接搜索。</p>
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

.picker-panel--embedded .picker-hint {
  margin-top: auto;
}

.picker-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.type-filter {
  width: 116px;
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  min-width: 140px;
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

.picker-hint {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}
</style>
