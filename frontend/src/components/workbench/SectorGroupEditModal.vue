<script setup lang="ts">
import { NButton, NCheckbox, NDataTable, NInput, NModal } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, ref, watch } from 'vue'

import SectorPickerPanel from '@/components/workbench/SectorPickerPanel.vue'
import {
  addSectorGroupMembers,
  MAX_GROUP_CHART_VISIBLE,
  MAX_GROUP_MEMBERS,
  removeSectorGroupMember,
  renameSectorGroup,
  setSectorGroupMemberChartVisible,
  type SectorGroup,
} from '@/api/sectorGroups'

const show = defineModel<boolean>('show', { required: true })

const props = defineProps<{
  group: SectorGroup | null
}>()

const emit = defineEmits<{
  updated: [group: SectorGroup]
}>()

const saving = ref(false)
const error = ref('')
const renameName = ref('')
const localGroup = ref<SectorGroup | null>(null)

const PANE_TABLE_HEIGHT = 380

const chartVisibleCount = computed(
  () => localGroup.value?.sectors.filter((sector) => sector.chart_visible).length ?? 0,
)

const memberColumns = computed<DataTableColumns<{ sector_id: string; name: string; chart_visible: boolean }>>(() => [
  { title: '板块', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '代码',
    key: 'sector_id',
    width: 88,
    render: (row: { sector_id: string }) =>
      h('span', { class: 'num text-[11px] text-[var(--muted)]' }, row.sector_id),
  },
  {
    title: '曲线',
    key: 'chart_visible',
    width: 52,
    align: 'center',
    render: (row: { sector_id: string; chart_visible: boolean }) =>
      h(NCheckbox, {
        size: 'small',
        checked: row.chart_visible,
        disabled: !row.chart_visible && chartVisibleCount.value >= MAX_GROUP_CHART_VISIBLE,
        onUpdateChecked: (value: boolean) => void toggleChart(row.sector_id, value),
      }),
  },
  {
    title: '',
    key: 'actions',
    width: 44,
    align: 'center',
    render: (row: { sector_id: string }) =>
      h(
        NButton,
        { size: 'tiny', quaternary: true, onClick: () => void removeMember(row.sector_id) },
        { default: () => '×' },
      ),
  },
])

watch(
  () => props.group,
  (group) => {
    localGroup.value = group ? { ...group, sectors: [...group.sectors], sector_ids: [...group.sector_ids] } : null
    renameName.value = group?.name ?? ''
    error.value = ''
  },
  { immediate: true },
)

async function saveRename() {
  if (!localGroup.value) return
  const cleaned = renameName.value.trim()
  if (!cleaned || cleaned === localGroup.value.name) return
  saving.value = true
  error.value = ''
  try {
    const group = await renameSectorGroup(localGroup.value.id, cleaned)
    localGroup.value = group
    emit('updated', group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function addMembers(sectorIds: string[]) {
  if (!localGroup.value || !sectorIds.length) return
  const remaining = MAX_GROUP_MEMBERS - localGroup.value.sector_ids.length
  if (remaining <= 0) {
    error.value = `分组已满（最多 ${MAX_GROUP_MEMBERS} 个板块）`
    return
  }
  saving.value = true
  error.value = ''
  try {
    const group = await addSectorGroupMembers(localGroup.value.id, sectorIds.slice(0, remaining))
    localGroup.value = group
    emit('updated', group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function removeMember(sectorId: string) {
  if (!localGroup.value) return
  saving.value = true
  error.value = ''
  try {
    const group = await removeSectorGroupMember(localGroup.value.id, sectorId)
    localGroup.value = group
    emit('updated', group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function toggleChart(sectorId: string, visible: boolean) {
  if (!localGroup.value) return
  saving.value = true
  error.value = ''
  try {
    const group = await setSectorGroupMemberChartVisible(localGroup.value.id, sectorId, visible)
    localGroup.value = group
    emit('updated', group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <NModal
    v-model:show="show"
    preset="card"
    :title="localGroup ? `编辑分组 · ${localGroup.name}` : '编辑分组'"
    class="group-edit-modal"
    :style="{ width: 'min(1040px, 96vw)' }"
    :mask-closable="!saving"
  >
    <p v-if="error" class="error-text">{{ error }}</p>

    <div v-if="localGroup" class="modal-body">
      <div class="modal-toolbar">
        <NInput v-model:value="renameName" size="small" placeholder="分组名称" class="name-input" />
        <NButton size="small" :loading="saving" @click="saveRename">保存名称</NButton>
        <span class="meta">
          曲线 {{ chartVisibleCount }}/{{ MAX_GROUP_CHART_VISIBLE }}
        </span>
      </div>

      <div class="modal-split">
        <section class="modal-pane modal-pane-left">
          <header class="pane-header">
            <span>已选板块</span>
            <span class="pane-count">{{ localGroup.sectors.length }}/{{ MAX_GROUP_MEMBERS }}</span>
          </header>
          <div class="pane-body">
            <NDataTable
              v-if="localGroup.sectors.length"
              size="small"
              :bordered="false"
              :columns="memberColumns"
              :data="localGroup.sectors"
              :max-height="PANE_TABLE_HEIGHT"
            />
            <p v-else class="pane-empty">暂无板块，在右侧浏览或搜索后添加</p>
          </div>
        </section>

        <section class="modal-pane modal-pane-right">
          <header class="pane-header">
            <span>浏览 / 搜索</span>
          </header>
          <div class="pane-body pane-body-picker">
            <SectorPickerPanel
              embedded
              :table-max-height="PANE_TABLE_HEIGHT"
              :excluded-ids="localGroup.sector_ids"
              @add="addMembers"
            />
          </div>
        </section>
      </div>
    </div>
  </NModal>
</template>

<style scoped src="./groupEditModal.css"></style>
