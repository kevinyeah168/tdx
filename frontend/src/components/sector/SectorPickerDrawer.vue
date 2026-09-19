<script setup lang="ts">
import { useDebounceFn, useWindowSize } from '@vueuse/core'
import {
  NButton,
  NCheckbox,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NPopconfirm,
  NScrollbar,
  NSelect,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'

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
import { fetchSectors } from '@/api/sectors'
import { invalidateSectorCatalogCache, MAX_CHART_SECTORS } from '@/api/workbenchBoard'
import { useBoardStore } from '@/stores/boardStore'
import { useSectorStore } from '@/stores/sectorStore'
import type { BoardCatalogType, BoardItem } from '@/types/board'
import { sectorTypeShort } from '@/utils/format'
import {
  applyAmbiguousSelection,
  collectCheckedSectorIds,
  matchPastedSectors,
  summarizePasteMatches,
  togglePasteRowChecked,
  type PasteMatchRow,
  type SectorCatalogItem,
} from '@/utils/sectorPasteMatch'
import {
  BOARD_TAB_TONE,
  sectorTypeClass,
} from '@/utils/sectorTypeStyles'

const boardStore = useBoardStore()
const sectorStore = useSectorStore()
const { pickerOpen, pickerType, pickerQuery, pickerCatalog, pickerSearchHint, activeSectorGroupId } =
  storeToRefs(boardStore)

const typeTabs: { label: string; value: BoardCatalogType }[] = [
  { label: '全部', value: 'ALL' },
  { label: '行业', value: 'HY' },
  { label: '概念', value: 'GN' },
  { label: '二级行业', value: 'HY2' },
  { label: '板块指数', value: 'IDX' },
  { label: '自定义', value: 'CUSTOM' },
]

const { width: windowWidth } = useWindowSize()
const drawerWidth = computed(() =>
  Math.min(Math.max(Math.round(windowWidth.value * 0.92), 1080), 1560),
)

const groups = ref<SectorGroup[]>([])
const groupsLoading = ref(false)
const groupSaving = ref(false)
const groupError = ref('')
const editingGroupId = ref('')
const newGroupName = ref('')
const renameName = ref('')
const groupsDirty = ref(false)
const pasteView = ref<'catalog' | 'paste'>('catalog')
const pasteText = ref('')
const pasteRows = ref<PasteMatchRow[]>([])
const pasteCatalog = ref<SectorCatalogItem[]>([])
const pasteMatching = ref(false)
const pasteAdding = ref(false)
const pasteError = ref('')

const editingGroup = computed(
  () => groups.value.find((group) => group.id === editingGroupId.value) ?? null,
)

const memberIds = computed(() => new Set(editingGroup.value?.sector_ids ?? []))

const chartVisibleCount = computed(
  () => editingGroup.value?.sectors.filter((sector) => sector.chart_visible).length ?? 0,
)

const chartLimitReached = computed(() => chartVisibleCount.value >= MAX_GROUP_CHART_VISIBLE)

const membersFull = computed(
  () => (editingGroup.value?.sectors.length ?? 0) >= MAX_GROUP_MEMBERS,
)

const remainingMemberSlots = computed(() =>
  Math.max(0, MAX_GROUP_MEMBERS - (editingGroup.value?.sectors.length ?? 0)),
)

const pasteSummary = computed(() => summarizePasteMatches(pasteRows.value))

const pasteSelectedCount = computed(() => collectCheckedSectorIds(pasteRows.value).length)

const pasteCanAdd = computed(
  () =>
    Boolean(editingGroup.value) &&
    pasteSelectedCount.value > 0 &&
    remainingMemberSlots.value > 0 &&
    !pasteAdding.value,
)

const catalogEmptyHint = computed(() => {
  if (pickerSearchHint.value) return pickerSearchHint.value
  if (pickerType.value === 'CUSTOM') return '还没有自定义板块，去设置页创建或导入'
  return '无匹配板块'
})

const debouncedSearch = useDebounceFn(() => {
  boardStore.loadCatalog()
}, 250)

watch(pickerType, () => {
  boardStore.loadCatalog()
})

watch(pickerQuery, () => {
  debouncedSearch()
})

watch(pickerOpen, (open) => {
  if (open) {
    invalidateSectorCatalogCache()
    groupsDirty.value = false
    pasteView.value = 'catalog'
    pasteText.value = ''
    pasteRows.value = []
    pasteError.value = ''
    pasteCatalog.value = []
    void loadGroups()
    void loadPasteCatalog()
  }
})

async function loadPasteCatalog() {
  try {
    const response = await fetchSectors({ limit: 1500 })
    pasteCatalog.value = response.items
  } catch {
    pasteCatalog.value = []
  }
}

async function loadGroups() {
  groupsLoading.value = true
  groupError.value = ''
  try {
    const response = await fetchSectorGroups()
    groups.value = response.items
    const preferred = activeSectorGroupId.value || response.active_group_id
    if (preferred && preferred !== 'all' && groups.value.some((group) => group.id === preferred)) {
      editingGroupId.value = preferred
    } else {
      editingGroupId.value = groups.value[0]?.id ?? ''
    }
    renameName.value = editingGroup.value?.name ?? ''
  } catch (error) {
    groupError.value = error instanceof Error ? error.message : String(error)
  } finally {
    groupsLoading.value = false
  }
}

function replaceGroup(group: SectorGroup) {
  const index = groups.value.findIndex((entry) => entry.id === group.id)
  if (index >= 0) groups.value.splice(index, 1, group)
  else groups.value.push(group)
  groupsDirty.value = true
}

function selectEditingGroup(groupId: string) {
  editingGroupId.value = groupId
  renameName.value = editingGroup.value?.name ?? ''
}

function setType(value: BoardCatalogType) {
  pickerType.value = value
}

function typeLabel(item: BoardItem) {
  return sectorTypeShort(item.sector_type, item.id)
}

function toneClass(item: BoardItem) {
  return sectorTypeClass(item.sector_type, item.id)
}

function tabToneClass(tab: BoardCatalogType) {
  return `sector-tone-${BOARD_TAB_TONE[tab] ?? 'default'}`
}

async function createGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  groupSaving.value = true
  groupError.value = ''
  try {
    const group = await createSectorGroup(name)
    replaceGroup(group)
    editingGroupId.value = group.id
    renameName.value = group.name
    newGroupName.value = ''
  } catch (error) {
    groupError.value = error instanceof Error ? error.message : String(error)
  } finally {
    groupSaving.value = false
  }
}

async function saveRename() {
  if (!editingGroup.value) return
  groupSaving.value = true
  groupError.value = ''
  try {
    const group = await renameSectorGroup(editingGroup.value.id, renameName.value)
    replaceGroup(group)
  } catch (error) {
    groupError.value = error instanceof Error ? error.message : String(error)
  } finally {
    groupSaving.value = false
  }
}

async function removeGroup(groupId: string) {
  groupSaving.value = true
  groupError.value = ''
  try {
    await deleteSectorGroup(groupId)
    groups.value = groups.value.filter((group) => group.id !== groupId)
    groupsDirty.value = true
    if (editingGroupId.value === groupId) {
      editingGroupId.value = groups.value[0]?.id ?? ''
      renameName.value = editingGroup.value?.name ?? ''
    }
  } catch (error) {
    groupError.value = error instanceof Error ? error.message : String(error)
  } finally {
    groupSaving.value = false
  }
}

async function addMember(item: BoardItem) {
  if (!editingGroup.value || memberIds.value.has(item.id) || membersFull.value) return
  groupSaving.value = true
  groupError.value = ''
  try {
    const group = await addSectorGroupMembers(editingGroup.value.id, [item.id])
    replaceGroup(group)
  } catch (error) {
    groupError.value = error instanceof Error ? error.message : String(error)
  } finally {
    groupSaving.value = false
  }
}

async function removeMember(sectorId: string) {
  if (!editingGroup.value) return
  groupSaving.value = true
  groupError.value = ''
  try {
    const group = await removeSectorGroupMember(editingGroup.value.id, sectorId)
    replaceGroup(group)
  } catch (error) {
    groupError.value = error instanceof Error ? error.message : String(error)
  } finally {
    groupSaving.value = false
  }
}

async function toggleMemberChart(sectorId: string, visible: boolean) {
  if (!editingGroup.value) return
  groupSaving.value = true
  groupError.value = ''
  try {
    const group = await setSectorGroupMemberChartVisible(editingGroup.value.id, sectorId, visible)
    replaceGroup(group)
  } catch (error) {
    groupError.value = error instanceof Error ? error.message : String(error)
  } finally {
    groupSaving.value = false
  }
}

function openPasteView() {
  if (!editingGroup.value) {
    groupError.value = '请先创建并选择一个分组'
    return
  }
  pasteView.value = 'paste'
  pasteError.value = ''
}

function closePasteView() {
  pasteView.value = 'catalog'
  pasteError.value = ''
  pasteRows.value = []
}

function backToPasteEdit() {
  pasteRows.value = []
  pasteError.value = ''
}

async function runPasteMatch() {
  if (!pasteText.value.trim()) {
    pasteError.value = '请先粘贴板块名称或代码'
    return
  }
  pasteMatching.value = true
  pasteError.value = ''
  try {
    await loadPasteCatalog()
    if (!pasteCatalog.value.length) {
      pasteError.value = '板块目录加载失败，请稍后重试'
      return
    }
    pasteRows.value = matchPastedSectors(
      pasteText.value,
      pasteCatalog.value,
      memberIds.value,
    )
    if (!pasteRows.value.length) {
      pasteError.value = '未识别到有效条目，请检查粘贴内容'
    }
  } finally {
    pasteMatching.value = false
  }
}

function onAmbiguousSelect(index: number, sectorId: string | null) {
  if (!sectorId) return
  pasteRows.value = applyAmbiguousSelection(pasteRows.value, index, sectorId, memberIds.value)
}

function onPasteRowToggle(index: number, checked: boolean) {
  pasteRows.value = togglePasteRowChecked(pasteRows.value, index, checked)
}

function pasteStatusLabel(status: PasteMatchRow['status']) {
  const map: Record<PasteMatchRow['status'], string> = {
    matched: '已匹配',
    ambiguous: '需确认',
    unmatched: '未识别',
    existing: '已在分组',
    duplicate: '重复',
  }
  return map[status]
}

function candidateOptions(row: PasteMatchRow) {
  return row.candidates.map((item) => ({
    label: `${item.name} (${item.sector_id})`,
    value: item.sector_id,
  }))
}

function resolvedSectorName(row: PasteMatchRow) {
  if (!row.selectedId) return '—'
  const hit =
    row.candidates.find((item) => item.sector_id === row.selectedId) ??
    pasteCatalog.value.find((item) => item.sector_id === row.selectedId)
  return hit ? `${hit.name} (${hit.sector_id})` : row.selectedId
}

async function confirmPasteAdd() {
  if (!editingGroup.value || !pasteCanAdd.value) return
  const ids = collectCheckedSectorIds(pasteRows.value).slice(0, remainingMemberSlots.value)
  if (!ids.length) return
  pasteAdding.value = true
  pasteError.value = ''
  try {
    const group = await addSectorGroupMembers(editingGroup.value.id, ids)
    replaceGroup(group)
    pasteView.value = 'catalog'
    pasteText.value = ''
    pasteRows.value = []
  } catch (error) {
    pasteError.value = error instanceof Error ? error.message : String(error)
  } finally {
    pasteAdding.value = false
  }
}

async function handleClose() {
  if (groupsDirty.value) {
    await sectorStore.loadGroups()
    await boardStore.closePicker(true)
  } else {
    await boardStore.closePicker(false)
  }
}
</script>

<template>
  <NDrawer
    :show="pickerOpen"
    :width="drawerWidth"
    placement="right"
    :trap-focus="false"
    display-directive="show"
    @update:show="(v) => !v && handleClose()"
  >
    <NDrawerContent :bordered="false" closable class="picker-drawer">
      <template #header>
        <div class="drawer-head">
          <div>
            <div class="drawer-title">管理分组</div>
            <div class="drawer-sub">
              首页按分组展示板块曲线；每组最多 {{ MAX_GROUP_MEMBERS }} 个板块，曲线最多
              {{ MAX_CHART_SECTORS }} 条
            </div>
          </div>
        </div>
      </template>

      <div class="picker-shell">
        <aside class="picker-sidebar">
          <section class="sidebar-section">
            <div class="section-label">分组列表</div>
            <div class="group-pills">
              <button
                v-for="group in groups"
                :key="group.id"
                type="button"
                class="group-pill"
                :class="{ active: editingGroupId === group.id }"
                @click="selectEditingGroup(group.id)"
              >
                {{ group.name }}
                <span class="pill-count">{{ group.sector_ids.length }}</span>
              </button>
            </div>
            <div class="group-create">
              <NInput
                v-model:value="newGroupName"
                size="small"
                placeholder="新分组名称"
                @keyup.enter="createGroup"
              />
              <NButton size="small" type="primary" :loading="groupSaving" @click="createGroup">
                新建
              </NButton>
            </div>

            <div v-if="groupsLoading" class="sidebar-hint">加载分组…</div>
            <p v-if="groupError" class="sidebar-error">{{ groupError }}</p>

            <div v-if="editingGroup" class="group-panel">
              <div class="rename-row">
                <NInput v-model:value="renameName" size="small" placeholder="分组名称" />
                <NButton size="small" :loading="groupSaving" @click="saveRename">重命名</NButton>
                <NPopconfirm @positive-click="removeGroup(editingGroup.id)">
                  <template #trigger>
                    <NButton size="small" type="error" secondary :loading="groupSaving">删除</NButton>
                  </template>
                  确定删除「{{ editingGroup.name }}」？
                </NPopconfirm>
              </div>

              <div class="member-meta">
                成员 {{ editingGroup.sectors.length }}/{{ MAX_GROUP_MEMBERS }} · 曲线
                {{ chartVisibleCount }}/{{ MAX_CHART_SECTORS }}
              </div>

              <NScrollbar v-if="editingGroup.sectors.length" class="member-scroll">
                <div class="member-list">
                  <div
                    v-for="sector in editingGroup.sectors"
                    :key="sector.sector_id"
                    class="member-row"
                  >
                    <div class="member-main">
                      <span class="member-name">{{ sector.name }}</span>
                      <span class="member-code num">{{ sector.sector_id }}</span>
                    </div>
                    <div class="member-actions">
                      <NCheckbox
                        :checked="sector.chart_visible"
                        :disabled="!sector.chart_visible && chartLimitReached"
                        @update:checked="(v) => toggleMemberChart(sector.sector_id, Boolean(v))"
                      >
                        曲线
                      </NCheckbox>
                      <button
                        type="button"
                        class="sector-chip-close"
                        aria-label="移除"
                        @click="removeMember(sector.sector_id)"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                </div>
              </NScrollbar>
              <div v-else class="sidebar-hint">分组为空，在右侧板块库点选添加</div>
            </div>

            <NEmpty v-else-if="!groupsLoading" description="请先创建分组" size="small" />
          </section>
        </aside>

        <div class="picker-main" :class="{ 'picker-main--paste': pasteView === 'paste' }">
          <template v-if="pasteView === 'catalog'">
            <div class="catalog-toolbar">
              <div class="catalog-toolbar-left">
                <div class="type-tabs">
                  <button
                    v-for="tab in typeTabs"
                    :key="tab.value"
                    type="button"
                    class="type-tab"
                    :class="[tabToneClass(tab.value), { active: pickerType === tab.value }]"
                    @click="setType(tab.value)"
                  >
                    <span class="type-tab-dot" aria-hidden="true" />
                    {{ tab.label }}
                  </button>
                </div>
              </div>

              <div class="catalog-toolbar-right">
                <NInput
                  :value="pickerQuery ?? ''"
                  clearable
                  size="medium"
                  placeholder="搜索名称或代码（全市场 1000+ 板块）"
                  class="search-input"
                  @update:value="(v) => (pickerQuery = v ?? '')"
                />
                <NButton
                  size="medium"
                  type="primary"
                  ghost
                  class="paste-entry-btn"
                  :disabled="!editingGroup"
                  @click="openPasteView"
                >
                  粘贴导入
                </NButton>
              </div>
            </div>

            <div v-if="!editingGroup" class="catalog-hint">请先创建并选择一个分组</div>
            <div v-else-if="membersFull" class="catalog-hint warn">
              当前分组已满 {{ MAX_GROUP_MEMBERS }} 个，请先移除成员再添加
            </div>

            <div class="grid-wrap">
              <NScrollbar v-if="pickerCatalog.length" class="grid-scroll">
                <div class="sector-grid">
                  <button
                    v-for="item in pickerCatalog"
                    :key="item.id"
                    type="button"
                    class="sector-tile"
                    :class="[
                      toneClass(item),
                      {
                        picked: memberIds.has(item.id),
                        disabled: !editingGroup || membersFull,
                      },
                    ]"
                    :disabled="!editingGroup || membersFull || groupSaving"
                    @click="addMember(item)"
                  >
                    <span class="tile-check" aria-hidden="true">
                      <svg
                        v-if="memberIds.has(item.id)"
                        viewBox="0 0 16 16"
                        width="12"
                        height="12"
                        fill="none"
                      >
                        <path
                          d="M3.5 8.2l2.8 2.8 6.2-6.4"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        />
                      </svg>
                    </span>
                    <span class="tile-name">{{ item.name }}</span>
                    <span class="tile-meta">
                      <span class="sector-type-badge tile-type-badge">{{ typeLabel(item) }}</span>
                      <span class="tile-code num">{{ item.id }}</span>
                    </span>
                  </button>
                </div>
              </NScrollbar>
              <NEmpty v-else class="py-12" :description="catalogEmptyHint" size="small" />
            </div>
          </template>

          <template v-else>
            <div class="paste-toolbar">
              <div class="paste-toolbar-title">
                <span class="paste-toolbar-label">粘贴导入</span>
                <span v-if="editingGroup" class="paste-toolbar-meta">
                  目标分组「{{ editingGroup.name }}」 · 还可添加 {{ remainingMemberSlots }} 个
                </span>
              </div>
            </div>

            <div v-if="!pasteRows.length" class="paste-input-card">
              <div class="paste-input-head">粘贴板块列表</div>
              <p class="paste-input-hint">
                支持名称、6 位代码、通达信公式行（如 C07:='880494';{互联网}）；换行/逗号/制表符分隔
              </p>
              <NInput
                v-model:value="pasteText"
                type="textarea"
                :rows="6"
                placeholder="例如：&#10;半导体&#10;880550&#10;C07:='880494';{互联网}"
              />
              <p v-if="pasteError" class="sidebar-error">{{ pasteError }}</p>
            </div>

            <div v-if="pasteRows.length" class="paste-result-card">
              <div class="paste-result-head">
                <span class="paste-result-stats">
                  识别 {{ pasteSummary.total }} 条 · 匹配 {{ pasteSummary.matched }} · 需确认
                  {{ pasteSummary.ambiguous }} · 未识别 {{ pasteSummary.unmatched }}
                </span>
                <span class="paste-result-selected">
                  已勾选 {{ pasteSelectedCount }} 个（底部确认导入）
                </span>
              </div>

              <NScrollbar class="paste-result-scroll">
                <div class="paste-result-list">
                  <div
                    v-for="(row, index) in pasteRows"
                    :key="`${row.token}-${index}`"
                    class="paste-result-row"
                    :class="`status-${row.status}`"
                  >
                    <NCheckbox
                      :checked="row.checked"
                      :disabled="
                        !row.selectedId ||
                        row.status === 'unmatched' ||
                        row.status === 'existing'
                      "
                      @update:checked="(v) => onPasteRowToggle(index, Boolean(v))"
                    />
                    <div class="paste-result-main">
                      <div class="paste-result-token">{{ row.token }}</div>
                      <div v-if="row.status === 'ambiguous'" class="paste-result-pick">
                        <NSelect
                          size="small"
                          placeholder="选择具体板块"
                          :options="candidateOptions(row)"
                          :value="row.selectedId"
                          @update:value="(v) => onAmbiguousSelect(index, v)"
                        />
                      </div>
                      <div v-else class="paste-result-target">{{ resolvedSectorName(row) }}</div>
                    </div>
                    <span class="paste-status-badge">{{ pasteStatusLabel(row.status) }}</span>
                  </div>
                </div>
              </NScrollbar>
            </div>
          </template>
        </div>
      </div>

      <template #footer>
        <div class="drawer-foot" :class="{ 'drawer-foot--paste': pasteView === 'paste' }">
          <template v-if="pasteView === 'paste' && pasteRows.length">
            <div class="paste-foot-info">
              <div class="paste-foot-title">确认导入到「{{ editingGroup?.name ?? '当前分组' }}」</div>
              <div class="paste-foot-meta">
                已勾选 {{ pasteSelectedCount }} 个 · 还可添加 {{ remainingMemberSlots }} 个
              </div>
            </div>
            <div class="paste-foot-actions">
              <NButton quaternary size="medium" @click="backToPasteEdit">返回编辑</NButton>
              <NButton
                type="primary"
                size="medium"
                class="paste-confirm-btn"
                :loading="pasteAdding"
                :disabled="!pasteCanAdd"
                @click="confirmPasteAdd"
              >
                确认导入 {{ Math.min(pasteSelectedCount, remainingMemberSlots) }} 个板块
              </NButton>
            </div>
          </template>

          <template v-else-if="pasteView === 'paste'">
            <span class="foot-hint">粘贴内容后，点击下方「识别匹配」查看结果</span>
            <div class="paste-foot-actions">
              <NButton quaternary size="medium" @click="closePasteView">返回板块库</NButton>
              <NButton
                type="primary"
                size="medium"
                :loading="pasteMatching"
                :disabled="!pasteText.trim()"
                @click="runPasteMatch"
              >
                识别匹配
              </NButton>
            </div>
          </template>

          <template v-else>
            <span class="foot-hint">修改已实时保存</span>
            <NButton type="primary" size="medium" @click="handleClose">完成</NButton>
          </template>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.picker-drawer :deep(.n-drawer-header) {
  padding: 20px 24px 14px;
  border-bottom: 1px solid var(--border);
}

.picker-drawer :deep(.n-drawer-body-content-wrapper) {
  padding: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.picker-drawer :deep(.n-drawer-footer) {
  padding: 14px 20px 18px;
  border-top: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 92%, var(--bg));
}

.drawer-head {
  padding-right: 8px;
}

.drawer-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text);
}

.drawer-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.45;
  max-width: 720px;
}

.picker-shell {
  display: flex;
  flex: 1;
  min-height: 0;
}

.picker-sidebar {
  flex: 0 0 340px;
  width: 340px;
  border-right: 1px solid var(--border);
  background: color-mix(in srgb, var(--muted) 3%, var(--panel));
  min-height: 0;
  overflow: auto;
}

.sidebar-section {
  padding: 14px 16px;
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin-bottom: 8px;
}

.group-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.group-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--muted);
  cursor: pointer;
}

.group-pill.active {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
  color: var(--accent);
  font-weight: 600;
}

.pill-count {
  font-size: 10px;
  opacity: 0.75;
}

.group-create {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 6px;
  margin-bottom: 10px;
}

.group-panel {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
}

.rename-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 6px;
}

.member-meta {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
}

.member-scroll {
  max-height: calc(100vh - 320px);
}

.member-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: 4px;
}

.member-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: color-mix(in srgb, var(--muted) 4%, var(--panel));
}

.member-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.member-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-code {
  font-size: 10px;
  color: var(--muted);
}

.member-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.member-actions :deep(.n-checkbox) {
  font-size: 11px;
}

.sidebar-hint {
  font-size: 12px;
  color: var(--muted);
}

.sidebar-error {
  margin: 6px 0 0;
  font-size: 11px;
  color: #e03030;
}

.picker-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 18px 10px;
  min-height: 0;
}

.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.catalog-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.catalog-toolbar-left {
  flex: 3;
  min-width: 0;
}

.catalog-toolbar-right {
  flex: 2;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.type-tabs {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  width: 100%;
  padding: 4px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--muted) 8%, transparent);
}

.type-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  flex: 1 1 0;
  min-width: 0;
  height: 34px;
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.type-tab-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--sector-tone);
  opacity: 0.72;
}

.type-tab.active {
  background: var(--sector-tone-soft);
  border-color: var(--sector-tone-border);
  color: var(--sector-tone);
  font-weight: 700;
}

.search-input {
  flex: 1;
  min-width: 0;
}

.paste-entry-btn {
  flex-shrink: 0;
}

.catalog-hint {
  font-size: 12px;
  color: var(--muted);
}

.catalog-hint.warn {
  color: #d03050;
}

.grid-wrap {
  flex: 1;
  min-height: 240px;
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  background: var(--panel);
}

.grid-scroll {
  height: 100%;
  max-height: calc(100vh - 240px);
}

.sector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
  padding: 14px;
}

.sector-tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  width: 100%;
  min-height: 64px;
  padding: 9px 10px 9px 36px;
  border: 1px solid var(--sector-tone-border);
  border-radius: 11px;
  background: color-mix(in srgb, var(--sector-tone-soft) 55%, var(--panel));
  text-align: left;
  cursor: pointer;
  position: relative;
}

.sector-tile.picked {
  border-color: var(--sector-tone);
  background: var(--sector-tone-soft);
}

.sector-tile:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.tile-check {
  position: absolute;
  left: 10px;
  top: 10px;
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  border: 1.5px solid var(--sector-tone-border);
  color: transparent;
  background: var(--panel);
}

.sector-tile.picked .tile-check {
  border-color: var(--sector-tone);
  background: var(--sector-tone);
  color: #fff;
}

.tile-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tile-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}

.tile-type-badge {
  font-size: 9px;
  padding: 1px 4px;
}

.tile-code {
  font-size: 10px;
  color: var(--muted);
}

.sector-chip-close {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 16px;
  cursor: pointer;
}

.sector-chip-close:hover {
  color: var(--danger, #d03050);
}

.paste-entry-btn {
  flex-shrink: 0;
}

.drawer-foot {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.drawer-foot--paste {
  align-items: flex-end;
  padding-top: 2px;
}

.foot-hint {
  font-size: 12px;
  color: var(--muted);
}

.paste-foot-info {
  min-width: 0;
}

.paste-foot-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.paste-foot-meta {
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted);
}

.paste-foot-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.paste-confirm-btn {
  min-width: 180px;
  font-weight: 600;
}

.paste-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.paste-toolbar-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.paste-toolbar-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.paste-toolbar-meta {
  font-size: 12px;
  color: var(--muted);
}

.picker-main--paste {
  gap: 10px;
}

.paste-input-card,
.paste-result-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel);
  padding: 12px 14px;
}

.paste-input-head,
.paste-result-head {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.paste-input-hint {
  margin: 6px 0 10px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.45;
}

.paste-result-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.paste-result-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}

.paste-result-stats {
  font-size: 12px;
  color: var(--muted);
}

.paste-result-selected {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}

.paste-result-scroll {
  flex: 1;
  min-height: 0;
  max-height: calc(100vh - 300px);
}

.paste-result-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.paste-result-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--muted) 3%, var(--panel));
}

.paste-result-row.status-unmatched,
.paste-result-row.status-existing {
  opacity: 0.72;
}

.paste-result-main {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.paste-result-token {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.paste-result-target {
  font-size: 11px;
  color: var(--muted);
}

.paste-result-pick {
  max-width: 360px;
}

.paste-status-badge {
  font-size: 10px;
  font-weight: 600;
  color: var(--accent);
  white-space: nowrap;
}

.paste-result-row.status-unmatched .paste-status-badge {
  color: #d03050;
}

.paste-result-row.status-existing .paste-status-badge,
.paste-result-row.status-duplicate .paste-status-badge {
  color: var(--muted);
}

@media (max-width: 900px) {
  .picker-shell {
    flex-direction: column;
  }

  .picker-sidebar {
    width: 100%;
    max-height: 42vh;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }

  .rename-row {
    grid-template-columns: 1fr;
  }
}
</style>
