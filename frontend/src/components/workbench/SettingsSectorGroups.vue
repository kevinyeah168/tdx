<script setup lang="ts">
import { NButton, NDataTable, NEmpty, NPopconfirm, NSpin } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'

import MemberTagsCell from '@/components/workbench/MemberTagsCell.vue'
import SectorGroupEditModal from '@/components/workbench/SectorGroupEditModal.vue'
import {
  createSectorGroup,
  deleteSectorGroup,
  fetchSectorGroups,
  type SectorGroup,
} from '@/api/sectorGroups'

const emit = defineEmits<{
  changed: []
}>()

type OverviewRow = {
  id: string
  name: string
  memberNames: string[]
  group: SectorGroup
}

const TABLE_MAX_HEIGHT = 480

const loading = ref(false)
const error = ref('')
const groups = ref<SectorGroup[]>([])
const editOpen = ref(false)
const editingGroup = ref<SectorGroup | null>(null)

const overviewRows = computed<OverviewRow[]>(() =>
  groups.value.map((group) => ({
    id: group.id,
    name: group.name,
    memberNames: (group.sectors ?? []).map((sector) => sector.name),
    group,
  })),
)

const columns = computed<DataTableColumns<OverviewRow>>(() => [
  { title: '分组名', key: 'name', width: 108, ellipsis: { tooltip: true } },
  {
    title: '包含的板块',
    key: 'memberNames',
    minWidth: 280,
    render: (row) =>
      h(MemberTagsCell, {
        names: row.memberNames,
        modalTitle: `${row.name} · 包含的板块`,
      }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 108,
    align: 'center',
    render: (row) =>
      h('div', { class: 'action-cell' }, [
        h(
          NButton,
          { size: 'tiny', quaternary: true, type: 'primary', onClick: () => openEdit(row.group) },
          { default: () => '编辑' },
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => void removeGroup(row.id) },
          {
            trigger: () =>
              h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, { default: () => '删除' }),
            default: () => `确定删除「${row.name}」？`,
          },
        ),
      ]),
  },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetchSectorGroups()
    groups.value = response.items
    if (editingGroup.value) {
      editingGroup.value = groups.value.find((group) => group.id === editingGroup.value?.id) ?? null
    }
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
  if (editingGroup.value?.id === group.id) {
    editingGroup.value = group
  }
  emit('changed')
}

async function createGroup(name: string) {
  const cleaned = name.trim()
  if (!cleaned) return
  error.value = ''
  try {
    const group = await createSectorGroup(cleaned)
    replaceGroup(group)
    openEdit(group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
    throw saveError
  }
}

async function removeGroup(groupId: string) {
  error.value = ''
  try {
    await deleteSectorGroup(groupId)
    groups.value = groups.value.filter((group) => group.id !== groupId)
    if (editingGroup.value?.id === groupId) {
      editingGroup.value = null
      editOpen.value = false
    }
    emit('changed')
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  }
}

function openEdit(group: SectorGroup) {
  editingGroup.value = group
  editOpen.value = true
}

function onGroupUpdated(group: SectorGroup) {
  replaceGroup(group)
}

onMounted(() => {
  void load()
})

defineExpose({ createGroup })
</script>

<template>
  <div class="overview-panel">
    <p v-if="error" class="error-text">{{ error }}</p>

    <div v-if="loading && !overviewRows.length" class="overview-empty">
      <NSpin size="small" />
    </div>
    <div v-else-if="overviewRows.length" class="overview-table-wrap">
      <NDataTable
        size="small"
        :bordered="false"
        :single-line="false"
        :loading="loading"
        :columns="columns"
        :data="overviewRows"
        :max-height="TABLE_MAX_HEIGHT"
      />
    </div>
    <div v-else class="overview-empty">
      <NEmpty description="暂无板块分组，在上方创建" size="small" />
    </div>

    <SectorGroupEditModal
      v-model:show="editOpen"
      :group="editingGroup"
      @updated="onGroupUpdated"
    />
  </div>
</template>

<style scoped src="./settingsOverview.css"></style>

