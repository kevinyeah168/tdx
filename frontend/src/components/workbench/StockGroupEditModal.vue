<script setup lang="ts">
import { NButton, NDataTable, NInput, NModal } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, ref, watch } from 'vue'

import StockGroupBatchImport from '@/components/workbench/StockGroupBatchImport.vue'
import StockPickerPanel from '@/components/workbench/StockPickerPanel.vue'
import {
  addStockGroupMembers,
  fetchStockGroups,
  MAX_GROUP_MEMBERS,
  removeStockGroupMember,
  renameStockGroup,
  type StockGroup,
} from '@/api/stockGroups'

const show = defineModel<boolean>('show', { required: true })

const props = defineProps<{
  group: StockGroup | null
}>()

const emit = defineEmits<{
  updated: [group: StockGroup]
}>()

const saving = ref(false)
const error = ref('')
const renameName = ref('')
const localGroup = ref<StockGroup | null>(null)
const batchImportOpen = ref(false)

const PANE_TABLE_HEIGHT = 380

const memberColumns = computed<DataTableColumns<{ symbol: string; name: string }>>(() => [
  { title: '个股', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '代码',
    key: 'symbol',
    width: 96,
    render: (row: { symbol: string }) =>
      h('span', { class: 'num text-[11px] text-[var(--muted)]' }, row.symbol),
  },
  {
    title: '',
    key: 'actions',
    width: 44,
    align: 'center',
    render: (row: { symbol: string }) =>
      h(
        NButton,
        { size: 'tiny', quaternary: true, onClick: () => void removeMember(row.symbol) },
        { default: () => '×' },
      ),
  },
])

watch(
  () => props.group,
  (group) => {
    localGroup.value = group
      ? { ...group, symbols: [...group.symbols], symbol_ids: [...group.symbol_ids] }
      : null
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
    const group = await renameStockGroup(localGroup.value.id, cleaned)
    localGroup.value = group
    emit('updated', group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function addMembers(symbols: string[]) {
  if (!localGroup.value || !symbols.length) return
  const remaining = MAX_GROUP_MEMBERS - localGroup.value.symbol_ids.length
  if (remaining <= 0) {
    error.value = `分组已满（最多 ${MAX_GROUP_MEMBERS} 只个股）`
    return
  }
  saving.value = true
  error.value = ''
  try {
    const group = await addStockGroupMembers(localGroup.value.id, symbols.slice(0, remaining))
    localGroup.value = group
    emit('updated', group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function removeMember(symbol: string) {
  if (!localGroup.value) return
  saving.value = true
  error.value = ''
  try {
    const group = await removeStockGroupMember(localGroup.value.id, symbol)
    localGroup.value = group
    emit('updated', group)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function onBatchImported() {
  if (!localGroup.value) return
  const response = await fetchStockGroups()
  const hit = response.items.find((group) => group.id === localGroup.value!.id)
  if (!hit) return
  localGroup.value = hit
  emit('updated', hit)
}
</script>

<template>
  <NModal
    v-model:show="show"
    preset="card"
    :title="localGroup ? `编辑分组 · ${localGroup.name}` : '编辑分组'"
    class="group-edit-modal"
    :style="{ width: 'min(960px, 96vw)' }"
    :mask-closable="!saving"
  >
    <p v-if="error" class="error-text">{{ error }}</p>

    <div v-if="localGroup" class="modal-body">
      <div class="modal-toolbar">
        <NInput v-model:value="renameName" size="small" placeholder="分组名称" class="name-input" />
        <NButton size="small" :loading="saving" @click="saveRename">保存名称</NButton>
        <NButton size="small" secondary @click="batchImportOpen = true">批量导入</NButton>
      </div>

      <div class="modal-split">
        <section class="modal-pane modal-pane-left">
          <header class="pane-header">
            <span>已选个股</span>
            <span class="pane-count">{{ localGroup.symbols.length }}/{{ MAX_GROUP_MEMBERS }}</span>
          </header>
          <div class="pane-body">
            <NDataTable
              v-if="localGroup.symbols.length"
              size="small"
              :bordered="false"
              :columns="memberColumns"
              :data="localGroup.symbols"
              :max-height="PANE_TABLE_HEIGHT"
            />
            <p v-else class="pane-empty">暂无个股，在右侧搜索后添加</p>
          </div>
        </section>

        <section class="modal-pane modal-pane-right">
          <header class="pane-header">
            <span>搜索添加</span>
          </header>
          <div class="pane-body pane-body-picker">
            <StockPickerPanel
              embedded
              :table-max-height="PANE_TABLE_HEIGHT"
              :excluded-symbols="localGroup.symbol_ids"
              @add="addMembers"
            />
          </div>
        </section>
      </div>
    </div>

    <StockGroupBatchImport
      v-if="localGroup"
      v-model:show="batchImportOpen"
      :group-id="localGroup.id"
      :existing-count="localGroup.symbol_ids.length"
      @imported="onBatchImported"
    />
  </NModal>
</template>

<style scoped src="./groupEditModal.css"></style>
