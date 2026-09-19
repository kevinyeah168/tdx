<script setup lang="ts">
import { NButton, NDataTable, NInput, NModal } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, ref, watch } from 'vue'

import StockPickerPanel from '@/components/workbench/StockPickerPanel.vue'
import {
  addCustomSectorMembers,
  MAX_CUSTOM_SECTOR_MEMBERS,
  removeCustomSectorMember,
  renameCustomSector,
  type CustomSector,
} from '@/api/customSectors'

const show = defineModel<boolean>('show', { required: true })

const props = defineProps<{
  sector: CustomSector | null
}>()

const emit = defineEmits<{
  updated: [sector: CustomSector]
}>()

const saving = ref(false)
const error = ref('')
const renameName = ref('')
const localSector = ref<CustomSector | null>(null)

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
  () => props.sector,
  (sector) => {
    localSector.value = sector
      ? { ...sector, members: [...sector.members], symbols: [...sector.symbols] }
      : null
    renameName.value = sector?.name ?? ''
    error.value = ''
  },
  { immediate: true },
)

async function saveRename() {
  if (!localSector.value) return
  const cleaned = renameName.value.trim()
  if (!cleaned || cleaned === localSector.value.name) return
  saving.value = true
  error.value = ''
  try {
    const sector = await renameCustomSector(localSector.value.sector_id, cleaned)
    localSector.value = sector
    emit('updated', sector)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function addMembers(symbols: string[]) {
  if (!localSector.value || !symbols.length) return
  const remaining = MAX_CUSTOM_SECTOR_MEMBERS - localSector.value.symbols.length
  if (remaining <= 0) {
    error.value = `板块已满（最多 ${MAX_CUSTOM_SECTOR_MEMBERS} 只个股）`
    return
  }
  saving.value = true
  error.value = ''
  try {
    const sector = await addCustomSectorMembers(
      localSector.value.sector_id,
      symbols.slice(0, remaining),
    )
    localSector.value = sector
    emit('updated', sector)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function removeMember(symbol: string) {
  if (!localSector.value) return
  saving.value = true
  error.value = ''
  try {
    const sector = await removeCustomSectorMember(localSector.value.sector_id, symbol)
    localSector.value = sector
    emit('updated', sector)
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
    :title="localSector ? `编辑板块 · ${localSector.name}` : '编辑板块'"
    class="group-edit-modal"
    :style="{ width: 'min(960px, 96vw)' }"
    :mask-closable="!saving"
  >
    <p v-if="error" class="error-text">{{ error }}</p>

    <div v-if="localSector" class="modal-body">
      <div class="modal-toolbar">
        <NInput v-model:value="renameName" size="small" placeholder="板块名称" class="name-input" />
        <NButton size="small" :loading="saving" @click="saveRename">保存名称</NButton>
        <span class="meta">ID：{{ localSector.sector_id }}</span>
      </div>

      <div class="modal-split">
        <section class="modal-pane modal-pane-left">
          <header class="pane-header">
            <span>已选个股</span>
            <span class="pane-count">
              {{ localSector.members.length }}/{{ MAX_CUSTOM_SECTOR_MEMBERS }}
            </span>
          </header>
          <div class="pane-body">
            <NDataTable
              v-if="localSector.members.length"
              size="small"
              :bordered="false"
              :columns="memberColumns"
              :data="localSector.members"
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
              :excluded-symbols="localSector.symbols"
              @add="addMembers"
            />
          </div>
        </section>
      </div>
    </div>
  </NModal>
</template>

<style scoped src="./groupEditModal.css"></style>
