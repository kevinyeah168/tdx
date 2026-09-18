<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import {
  NButton,
  NCheckbox,
  NEmpty,
  NInput,
  NPopconfirm,
  NSelect,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'

import {
  addSectorGroupMembers,
  createSectorGroup,
  deleteSectorGroup,
  fetchSectorGroups,
  MAX_GROUP_CHART_VISIBLE,
  MAX_GROUP_MEMBERS,
  removeSectorGroupMember,
  renameSectorGroup,
  setSectorGroupMemberChartVisible,
  type SectorGroup,
} from '@/api/sectorGroups'
import { searchSectors } from '@/api/sectors'
import type { SectorSummary } from '@/types/api'

const emit = defineEmits<{
  changed: []
}>()

type SectorTypeFilter =
  | 'all'
  | 'industry'
  | 'concept'
  | 'industry2'
  | 'classic_index'
  | 'style'
  | 'region'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const groups = ref<SectorGroup[]>([])
const selectedGroupId = ref('')
const newGroupName = ref('')
const renameName = ref('')
const sectorSearch = ref('')
const sectorSearching = ref(false)
const sectorHits = ref<SectorSummary[]>([])
const selectedHitIds = ref<Set<string>>(new Set())
const sectorTypeFilter = ref<SectorTypeFilter>('all')

const typeFilterOptions = [
  { label: '全部类型', value: 'all' },
  { label: '行业', value: 'industry' },
  { label: '概念', value: 'concept' },
  { label: '二级行业', value: 'industry2' },
  { label: '板块指数', value: 'classic_index' },
  { label: '风格', value: 'style' },
  { label: '地域', value: 'region' },
]

const selectedGroup = computed(
  () => groups.value.find((group) => group.id === selectedGroupId.value) ?? null,
)

const chartVisibleCount = computed(
  () => selectedGroup.value?.sectors.filter((sector) => sector.chart_visible).length ?? 0,
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetchSectorGroups()
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

function replaceGroup(group: SectorGroup) {
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
    const group = await createSectorGroup(name)
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
    const group = await renameSectorGroup(selectedGroup.value.id, renameName.value)
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
    await deleteSectorGroup(groupId)
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

function toggleHit(sectorId: string, checked: boolean) {
  const next = new Set(selectedHitIds.value)
  if (checked) next.add(sectorId)
  else next.delete(sectorId)
  selectedHitIds.value = next
}

function selectAllHits() {
  selectedHitIds.value = new Set(sectorHits.value.map((item) => item.sector_id))
}

async function confirmAddSelected() {
  if (!selectedGroup.value || !selectedHitIds.value.size) return
  const remaining = MAX_GROUP_MEMBERS - selectedGroup.value.sector_ids.length
  if (remaining <= 0) {
    error.value = `分组已满（最多 ${MAX_GROUP_MEMBERS} 个板块）`
    return
  }
  const sectorIds = [...selectedHitIds.value].slice(0, remaining)
  saving.value = true
  error.value = ''
  try {
    const group = await addSectorGroupMembers(selectedGroup.value.id, sectorIds)
    replaceGroup(group)
    clearHitSelection()
    const existing = new Set(group.sector_ids)
    sectorHits.value = sectorHits.value.filter((item) => !existing.has(item.sector_id))
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function removeSector(sectorId: string) {
  if (!selectedGroup.value) return
  saving.value = true
  error.value = ''
  try {
    const group = await removeSectorGroupMember(selectedGroup.value.id, sectorId)
    replaceGroup(group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function toggleSectorChart(sectorId: string, visible: boolean) {
  if (!selectedGroup.value) return
  saving.value = true
  error.value = ''
  try {
    const group = await setSectorGroupMemberChartVisible(selectedGroup.value.id, sectorId, visible)
    replaceGroup(group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

function filterHitsByType(items: SectorSummary[]): SectorSummary[] {
  if (sectorTypeFilter.value === 'all') return items
  return items.filter((item) => item.sector_type === sectorTypeFilter.value)
}

const runSectorSearch = useDebounceFn(async (query: string) => {
  const trimmed = query.trim()
  if (!trimmed) {
    sectorHits.value = []
    return
  }
  sectorSearching.value = true
  try {
    const response = await searchSectors(trimmed, 80)
    const existing = new Set(selectedGroup.value?.sector_ids ?? [])
    sectorHits.value = filterHitsByType(
      response.items.filter((item) => !existing.has(item.sector_id)),
    )
  } catch {
    sectorHits.value = []
  } finally {
    sectorSearching.value = false
  }
}, 250)

function onSectorSearchInput(value: string) {
  sectorSearch.value = value
  clearHitSelection()
  void runSectorSearch(value)
}

function onTypeFilterChange() {
  clearHitSelection()
  if (sectorSearch.value.trim()) {
    void runSectorSearch(sectorSearch.value)
  } else {
    sectorHits.value = []
  }
}

function selectGroup(groupId: string) {
  selectedGroupId.value = groupId
  renameName.value = selectedGroup.value?.name ?? ''
  sectorSearch.value = ''
  sectorHits.value = []
  sectorTypeFilter.value = 'all'
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
    <p class="hint">每组最多 {{ MAX_GROUP_MEMBERS }} 板块 · 曲线 {{ MAX_GROUP_CHART_VISIBLE }} 条</p>

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
            <span class="count">{{ group.sector_ids.length }}</span>
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
          <NSelect
            v-model:value="sectorTypeFilter"
            class="type-filter"
            size="small"
            :options="typeFilterOptions"
            @update:value="onTypeFilterChange"
          />
          <NInput
            :value="sectorSearch"
            class="search-input"
            size="small"
            placeholder="搜索板块加入"
            clearable
            @update:value="onSectorSearchInput"
          />
          <span class="group-settings-meta">
            成员 {{ selectedGroup.sectors.length }}/{{ MAX_GROUP_MEMBERS }} · 曲线
            {{ chartVisibleCount }}/{{ MAX_GROUP_CHART_VISIBLE }}
          </span>
        </div>

        <div v-if="sectorSearch.trim()" class="group-settings-search-panel">
          <div class="group-settings-search-toolbar">
            <span class="hint">
              <template v-if="sectorSearching">搜索中…</template>
              <template v-else-if="sectorHits.length">共 {{ sectorHits.length }} 条 · 已选 {{ selectedHitIds.size }}</template>
              <template v-else>无匹配</template>
            </span>
            <div class="group-settings-search-actions">
              <NButton size="tiny" quaternary :disabled="!sectorHits.length" @click="selectAllHits">
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
          <div v-if="sectorHits.length" class="group-settings-search-results">
            <label
              v-for="item in sectorHits"
              :key="item.sector_id"
              class="group-settings-search-option"
            >
              <NCheckbox
                size="small"
                :checked="selectedHitIds.has(item.sector_id)"
                @update:checked="(checked) => toggleHit(item.sector_id, Boolean(checked))"
              />
              <span class="option-name">{{ item.name }}</span>
              <span class="muted">{{ item.sector_id }}</span>
            </label>
          </div>
        </div>

        <div v-if="selectedGroup.sectors.length" class="group-settings-member-scroll">
          <div class="group-settings-member-grid">
            <div
              v-for="sector in selectedGroup.sectors"
              :key="sector.sector_id"
              class="group-settings-member-chip"
            >
              <div class="chip-main">
                <span class="chip-name">{{ sector.name }}</span>
                <span class="chip-sub">{{ sector.sector_id }}</span>
              </div>
              <div class="chip-actions">
                <NCheckbox
                  size="small"
                  :checked="sector.chart_visible"
                  :disabled="!sector.chart_visible && chartVisibleCount >= MAX_GROUP_CHART_VISIBLE"
                  @update:checked="(v) => toggleSectorChart(sector.sector_id, Boolean(v))"
                />
                <NButton size="tiny" quaternary @click="removeSector(sector.sector_id)">×</NButton>
              </div>
            </div>
          </div>
        </div>
        <NEmpty v-else description="分组为空" size="small" />
      </section>
    </div>

    <NEmpty v-else description="尚未创建分组" size="small" />
  </div>
</template>

<style scoped src="./settingsGroupLayout.css"></style>
