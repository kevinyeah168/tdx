<script setup lang="ts">
import { NButton, NDataTable, NEmpty, NPopconfirm, NSpin } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'

import MemberTagsCell from '@/components/workbench/MemberTagsCell.vue'
import StockGroupEditModal from '@/components/workbench/StockGroupEditModal.vue'
import {
  createStockGroup,
  deleteStockGroup,
  fetchStockGroups,
  type StockGroup,
} from '@/api/stockGroups'

const emit = defineEmits<{
  changed: []
}>()

type OverviewRow = {
  id: string
  name: string
  memberNames: string[]
  group: StockGroup
}

const TABLE_MAX_HEIGHT = 480

const loading = ref(false)
const error = ref('')
const groups = ref<StockGroup[]>([])
const editOpen = ref(false)
const editingGroup = ref<StockGroup | null>(null)

const overviewRows = computed<OverviewRow[]>(() =>
  groups.value.map((group) => ({
    id: group.id,
    name: group.name,
    memberNames: (group.symbols ?? []).map((stock) => stock.name),
    group,
  })),
)

const columns = computed<DataTableColumns<OverviewRow>>(() => [
  { title: '分组名', key: 'name', width: 108, ellipsis: { tooltip: true } },
  {
    title: '包含的个股',
    key: 'memberNames',
    minWidth: 280,
    render: (row) =>
      h(MemberTagsCell, {
        names: row.memberNames,
        modalTitle: `${row.name} · 包含的个股`,
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
    const response = await fetchStockGroups()
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

function replaceGroup(group: StockGroup) {
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
    const group = await createStockGroup(cleaned)
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
    await deleteStockGroup(groupId)
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

function openEdit(group: StockGroup) {
  editingGroup.value = group
  editOpen.value = true
}

function onGroupUpdated(group: StockGroup) {
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
      <NEmpty description="暂无个股分组，在上方创建" size="small" />
    </div>

    <StockGroupEditModal
      v-model:show="editOpen"
      :group="editingGroup"
      @updated="onGroupUpdated"
    />
  </div>
</template>

<style scoped src="./settingsOverview.css"></style>

