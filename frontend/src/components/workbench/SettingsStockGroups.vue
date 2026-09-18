<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import {
  NButton,
  NCheckbox,
  NEmpty,
  NInput,
  NPopconfirm,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'

import StockGroupBatchImport from '@/components/workbench/StockGroupBatchImport.vue'
import { apiGet } from '@/api/client'
import {
  addStockGroupMembers,
  createStockGroup,
  deleteStockGroup,
  fetchStockGroups,
  MAX_GROUP_MEMBERS,
  removeStockGroupMember,
  renameStockGroup,
  type StockGroup,
} from '@/api/stockGroups'
import type { SearchResponse } from '@/types/api'

const emit = defineEmits<{
  changed: []
}>()

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const groups = ref<StockGroup[]>([])
const selectedGroupId = ref('')
const newGroupName = ref('')
const renameName = ref('')
const stockSearch = ref('')
const stockSearching = ref(false)
const stockHits = ref<Array<{ symbol: string; name: string }>>([])
const selectedHitIds = ref<Set<string>>(new Set())
const batchImportOpen = ref(false)

const selectedGroup = computed(
  () => groups.value.find((group) => group.id === selectedGroupId.value) ?? null,
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetchStockGroups()
    groups.value = response.items
    if (!selectedGroupId.value && groups.value.length) {
      selectedGroupId.value = groups.value[0]!.id
    } else if (
      selectedGroupId.value &&
      !groups.value.some((group) => group.id === selectedGroupId.value)
    ) {
      selectedGroupId.value = groups.value[0]?.id ?? ''
    }
    renameName.value = selectedGroup.value?.name ?? ''
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : String(loadError)
  } finally {
    loading.value = false
  }
}

function replaceGroup(group: StockGroup) {
  const index = groups.value.findIndex((entry) => entry.id === group.id)
  if (index >= 0) groups.value.splice(index, 1, group)
  else groups.value.push(group)
  emit('changed')
}

async function createGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  saving.value = true
  error.value = ''
  try {
    const group = await createStockGroup(name)
    replaceGroup(group)
    selectedGroupId.value = group.id
    renameName.value = group.name
    newGroupName.value = ''
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function saveRename() {
  if (!selectedGroup.value) return
  saving.value = true
  error.value = ''
  try {
    const group = await renameStockGroup(selectedGroup.value.id, renameName.value)
    replaceGroup(group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function removeGroup(groupId: string) {
  saving.value = true
  error.value = ''
  try {
    await deleteStockGroup(groupId)
    groups.value = groups.value.filter((group) => group.id !== groupId)
    if (selectedGroupId.value === groupId) {
      selectedGroupId.value = groups.value[0]?.id ?? ''
      renameName.value = groups.value[0]?.name ?? ''
    }
    emit('changed')
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

function clearHitSelection() {
  selectedHitIds.value = new Set()
}

function toggleHit(symbol: string, checked: boolean) {
  const next = new Set(selectedHitIds.value)
  if (checked) next.add(symbol)
  else next.delete(symbol)
  selectedHitIds.value = next
}

function selectAllHits() {
  selectedHitIds.value = new Set(stockHits.value.map((item) => item.symbol))
}

async function confirmAddSelected() {
  if (!selectedGroup.value || !selectedHitIds.value.size) return
  const remaining = MAX_GROUP_MEMBERS - selectedGroup.value.symbol_ids.length
  if (remaining <= 0) {
    error.value = `分组已满（最多 ${MAX_GROUP_MEMBERS} 只个股）`
    return
  }
  const symbols = [...selectedHitIds.value].slice(0, remaining)
  saving.value = true
  error.value = ''
  try {
    const group = await addStockGroupMembers(selectedGroup.value.id, symbols)
    replaceGroup(group)
    clearHitSelection()
    const existing = new Set(group.symbol_ids)
    stockHits.value = stockHits.value.filter((item) => !existing.has(item.symbol))
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function removeStock(symbol: string) {
  if (!selectedGroup.value) return
  saving.value = true
  error.value = ''
  try {
    const group = await removeStockGroupMember(selectedGroup.value.id, symbol)
    replaceGroup(group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

const runStockSearch = useDebounceFn(async (query: string) => {
  const trimmed = query.trim()
  if (!trimmed) {
    stockHits.value = []
    return
  }
  stockSearching.value = true
  try {
    const response = await apiGet<SearchResponse>('/api/v1/market/search', { q: trimmed })
    const existing = new Set(selectedGroup.value?.symbol_ids ?? [])
    stockHits.value = response.results
      .filter((item) => !existing.has(item.symbol.toUpperCase()))
      .map((item) => ({ symbol: item.symbol.toUpperCase(), name: item.name }))
  } catch {
    stockHits.value = []
  } finally {
    stockSearching.value = false
  }
}, 250)

function onStockSearchInput(value: string) {
  stockSearch.value = value
  clearHitSelection()
  void runStockSearch(value)
}

function selectGroup(groupId: string) {
  selectedGroupId.value = groupId
  renameName.value = selectedGroup.value?.name ?? ''
  stockSearch.value = ''
  stockHits.value = []
  clearHitSelection()
}

onMounted(() => {
  void load()
})

defineExpose({ reload: load })
</script>

<template>
  <div class="group-settings">
    <p v-if="error" class="error-text">{{ error }}</p>
    <p class="hint">每组最多 {{ MAX_GROUP_MEMBERS }} 只个股</p>

    <div v-if="loading" class="hint">加载分组…</div>

    <div v-else-if="groups.length" class="group-settings-shell">
      <aside class="group-settings-nav">
        <div class="group-settings-nav-list">
          <button
            v-for="group in groups"
            :key="group.id"
            type="button"
            class="group-settings-nav-item"
            :class="{ active: group.id === selectedGroupId }"
            @click="selectGroup(group.id)"
          >
            <span class="truncate">{{ group.name }}</span>
            <span class="count">{{ group.symbol_ids.length }}</span>
          </button>
        </div>
        <div class="group-settings-create">
          <NInput
            v-model:value="newGroupName"
            size="small"
            placeholder="新分组"
            @keyup.enter="createGroup"
          />
          <NButton size="small" type="primary" :loading="saving" @click="createGroup">+</NButton>
        </div>
      </aside>

      <section v-if="selectedGroup" class="group-settings-main">
        <div class="group-settings-toolbar">
          <NInput
            v-model:value="renameName"
            class="name-input"
            size="small"
            placeholder="分组名称"
          />
          <NButton size="small" :loading="saving" @click="saveRename">重命名</NButton>
          <div class="spacer" />
          <NPopconfirm @positive-click="removeGroup(selectedGroup.id)">
            <template #trigger>
              <NButton size="small" quaternary type="error" :loading="saving">删除</NButton>
            </template>
            确定删除「{{ selectedGroup.name }}」？
          </NPopconfirm>
        </div>

        <div class="group-settings-add">
          <NInput
            :value="stockSearch"
            class="search-input"
            size="small"
            placeholder="搜索个股加入"
            clearable
            @update:value="onStockSearchInput"
          />
          <NButton size="small" secondary @click="batchImportOpen = true">批量导入</NButton>
          <span class="group-settings-meta">
            成员 {{ selectedGroup.symbols.length }}/{{ MAX_GROUP_MEMBERS }}
          </span>
        </div>

        <div v-if="stockSearch.trim()" class="group-settings-search-panel">
          <div class="group-settings-search-toolbar">
            <span class="hint">
              <template v-if="stockSearching">搜索中…</template>
              <template v-else-if="stockHits.length">共 {{ stockHits.length }} 条 · 已选 {{ selectedHitIds.size }}</template>
              <template v-else>无匹配</template>
            </span>
            <div class="group-settings-search-actions">
              <NButton size="tiny" quaternary :disabled="!stockHits.length" @click="selectAllHits">
                全选
              </NButton>
              <NButton size="tiny" quaternary :disabled="!selectedHitIds.size" @click="clearHitSelection">
                清空
              </NButton>
              <NButton
                size="small"
                type="primary"
                :disabled="!selectedHitIds.size"
                :loading="saving"
                @click="confirmAddSelected"
              >
                确认添加{{ selectedHitIds.size ? ` (${selectedHitIds.size})` : '' }}
              </NButton>
            </div>
          </div>
          <div v-if="stockHits.length" class="group-settings-search-results">
            <label
              v-for="item in stockHits"
              :key="item.symbol"
              class="group-settings-search-option"
            >
              <NCheckbox
                size="small"
                :checked="selectedHitIds.has(item.symbol)"
                @update:checked="(checked) => toggleHit(item.symbol, Boolean(checked))"
              />
              <span class="option-name">{{ item.name }}</span>
              <span class="muted">{{ item.symbol }}</span>
            </label>
          </div>
        </div>

        <div v-if="selectedGroup.symbols.length" class="group-settings-member-scroll">
          <div class="group-settings-member-grid">
            <div
              v-for="stock in selectedGroup.symbols"
              :key="stock.symbol"
              class="group-settings-member-chip"
            >
              <div class="chip-main">
                <span class="chip-name">{{ stock.name }}</span>
                <span class="chip-sub">{{ stock.symbol }}</span>
              </div>
              <NButton size="tiny" quaternary @click="removeStock(stock.symbol)">×</NButton>
            </div>
          </div>
        </div>
        <NEmpty v-else description="分组为空" size="small" />
      </section>
    </div>

    <NEmpty v-else description="尚未创建分组" size="small" />

    <StockGroupBatchImport
      v-if="selectedGroup"
      v-model:show="batchImportOpen"
      :group-id="selectedGroup.id"
      :existing-count="selectedGroup.symbol_ids.length"
      @imported="load"
    />
  </div>
</template>

<style scoped src="./settingsGroupLayout.css"></style>
