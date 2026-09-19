<script setup lang="ts">
import {
  NButton,
  NDataTable,
  NEmpty,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSwitch,
  NSpin,
  NTag,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'

import CustomSectorEditModal from '@/components/workbench/CustomSectorEditModal.vue'
import MemberTagsCell from '@/components/workbench/MemberTagsCell.vue'
import {
  createCustomSector,
  deleteCustomSector,
  fetchCustomSectorSyncConfig,
  fetchCustomSectors,
  pickCustomSectorDirectory,
  saveCustomSectorSyncConfig,
  syncCustomSectorDirectory,
  type CustomSector,
  type CustomSectorSyncConfig,
} from '@/api/customSectors'
import { invalidateSectorCatalogCache } from '@/api/workbenchBoard'

const emit = defineEmits<{
  changed: []
}>()

function notifyCatalogChanged() {
  invalidateSectorCatalogCache()
  emit('changed')
}

type OverviewRow = {
  sector_id: string
  name: string
  memberNames: string[]
  sector: CustomSector
}

const TABLE_MAX_HEIGHT = 480

const loading = ref(false)
const saving = ref(false)
const syncing = ref(false)
const pickingDirectory = ref(false)
const savingSyncConfig = ref(false)
const error = ref('')
const newSectorName = ref('')
const sectors = ref<CustomSector[]>([])
const editOpen = ref(false)
const editingSector = ref<CustomSector | null>(null)
const syncDirectoryPath = ref('')
const syncAutoEnabled = ref(false)
const syncIntervalSeconds = ref(60)
const syncConfig = ref<CustomSectorSyncConfig | null>(null)

const syncStatusText = computed(() => {
  const config = syncConfig.value
  if (!config?.last_sync_at) return '还没同步过'
  const summary = config.last_sync_summary
  const when = config.last_sync_at
  if (config.last_sync_error) return `${when} · 有点问题，再看看`
  if (!summary) return `${when} · 已同步`
  const parts = [`${summary.sectors_updated} 个板块`]
  if (summary.members_total) parts.push(`${summary.members_total} 只股票`)
  if ((summary.sectors_deleted ?? 0) > 0) parts.push(`删了 ${summary.sectors_deleted} 个`)
  return `${when} · ${parts.join('，')}`
})

const syncPathLabel = computed(() =>
  syncDirectoryPath.value.trim() || '点这里选通达信导出的文件夹',
)

const overviewRows = computed<OverviewRow[]>(() =>
  sectors.value.map((sector) => ({
    sector_id: sector.sector_id,
    name: sector.name,
    memberNames: sector.members.map((member) => member.name),
    sector,
  })),
)

const columns = computed<DataTableColumns<OverviewRow>>(() => [
  { title: '板块名', key: 'name', width: 96, ellipsis: { tooltip: true } },
  {
    title: '类型',
    key: 'source_type',
    width: 64,
    align: 'center',
    render: (row) =>
      h(
        NTag,
        {
          size: 'small',
          bordered: false,
          type: row.sector.source_type === 'directory' ? 'info' : 'default',
        },
        { default: () => (row.sector.source_type === 'directory' ? '导入' : '手动') },
      ),
  },
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
          { size: 'tiny', quaternary: true, type: 'primary', onClick: () => openEdit(row.sector) },
          { default: () => '编辑' },
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => void removeSector(row.sector_id) },
          {
            trigger: () =>
              h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, { default: () => '删除' }),
            default: () => `确定删除「${row.name}」？`,
          },
        ),
      ]),
  },
])

function applySyncConfig(config: CustomSectorSyncConfig) {
  syncConfig.value = config
  syncDirectoryPath.value = config.directory_path
  syncAutoEnabled.value = config.auto_sync_enabled
  syncIntervalSeconds.value = config.interval_seconds
}

async function loadSyncConfig() {
  try {
    applySyncConfig(await fetchCustomSectorSyncConfig())
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : String(loadError)
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [response] = await Promise.all([fetchCustomSectors(), loadSyncConfig()])
    sectors.value = response.items
    if (editingSector.value) {
      editingSector.value =
        sectors.value.find((sector) => sector.sector_id === editingSector.value?.sector_id) ?? null
    }
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : String(loadError)
  } finally {
    loading.value = false
  }
}

async function persistSyncConfig() {
  savingSyncConfig.value = true
  error.value = ''
  try {
    applySyncConfig(
      await saveCustomSectorSyncConfig({
        directory_path: syncDirectoryPath.value.trim(),
        auto_sync_enabled: syncAutoEnabled.value,
        interval_seconds: syncIntervalSeconds.value,
      }),
    )
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    savingSyncConfig.value = false
  }
}

async function chooseSyncDirectory() {
  pickingDirectory.value = true
  error.value = ''
  try {
    const result = await pickCustomSectorDirectory(syncDirectoryPath.value.trim())
    if (result.cancelled || !result.directory_path) return
    syncDirectoryPath.value = result.directory_path
    await persistSyncConfig()
  } catch (pickError) {
    error.value = pickError instanceof Error ? pickError.message : String(pickError)
  } finally {
    pickingDirectory.value = false
  }
}

async function runDirectorySync() {
  const directoryPath = syncDirectoryPath.value.trim()
  if (!directoryPath) {
    error.value = '先选个文件夹'
    return
  }
  syncing.value = true
  error.value = ''
  try {
    await persistSyncConfig()
    const result = await syncCustomSectorDirectory(directoryPath)
    sectors.value = result.items
    applySyncConfig(result.config)
    notifyCatalogChanged()
  } catch (syncError) {
    error.value = syncError instanceof Error ? syncError.message : String(syncError)
  } finally {
    syncing.value = false
  }
}

function replaceSector(sector: CustomSector) {
  const index = sectors.value.findIndex((entry) => entry.sector_id === sector.sector_id)
  if (index >= 0) sectors.value.splice(index, 1, sector)
  else sectors.value.push(sector)
  if (editingSector.value?.sector_id === sector.sector_id) {
    editingSector.value = sector
  }
  notifyCatalogChanged()
}

async function createSector() {
  const name = newSectorName.value.trim()
  if (!name) return
  saving.value = true
  error.value = ''
  try {
    const sector = await createCustomSector(name)
    replaceSector(sector)
    newSectorName.value = ''
    openEdit(sector)
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function removeSector(sectorId: string) {
  error.value = ''
  try {
    await deleteCustomSector(sectorId)
    sectors.value = sectors.value.filter((sector) => sector.sector_id !== sectorId)
    if (editingSector.value?.sector_id === sectorId) {
      editingSector.value = null
      editOpen.value = false
    }
    notifyCatalogChanged()
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  }
}

function openEdit(sector: CustomSector) {
  editingSector.value = sector
  editOpen.value = true
}

function onSectorUpdated(sector: CustomSector) {
  replaceSector(sector)
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="overview-panel">
    <div class="sector-top-split">
      <section class="sector-panel-card manual-card">
        <div class="sync-card-head">
          <div class="sync-card-title">
            <span class="sync-card-label">手动新建</span>
            <span class="sync-card-hint">自己起名、自己选股，最多 60 只</span>
          </div>
          <NButton
            size="small"
            type="primary"
            :loading="saving"
            :disabled="loading || !newSectorName.trim()"
            @click="createSector"
          >
            新建
          </NButton>
        </div>
        <NInput
          v-model:value="newSectorName"
          class="manual-name-input"
          size="small"
          placeholder="起个名字，回车也能建"
          :disabled="loading"
          @keyup.enter="createSector"
        />
      </section>

      <section class="sector-panel-card sync-card">
        <div class="sync-card-head">
          <div class="sync-card-title">
            <span class="sync-card-label">从文件导入</span>
            <span class="sync-card-hint">选通达信导出目录，文件名就是板块名</span>
          </div>
          <NButton
            size="small"
            type="primary"
            :loading="syncing"
            :disabled="loading || pickingDirectory"
            @click="runDirectorySync"
          >
            同步
          </NButton>
        </div>

        <button
          type="button"
          class="sync-path-picker"
          :class="{ 'is-empty': !syncDirectoryPath.trim() }"
          :disabled="loading || syncing || pickingDirectory"
          @click="chooseSyncDirectory"
        >
          <span class="sync-path-prefix">{{ pickingDirectory ? '…' : '目录' }}</span>
          <span class="sync-path-text">{{ syncPathLabel }}</span>
        </button>

        <div class="sync-card-foot">
          <div class="sync-auto-row">
            <NSwitch
              v-model:value="syncAutoEnabled"
              size="small"
              :disabled="loading || savingSyncConfig"
              @update:value="persistSyncConfig"
            />
            <span>自动同步</span>
            <template v-if="syncAutoEnabled">
              <span>每</span>
              <NInputNumber
                v-model:value="syncIntervalSeconds"
                size="small"
                :min="30"
                :max="600"
                :step="30"
                :show-button="false"
                :disabled="loading || savingSyncConfig"
                @blur="persistSyncConfig"
              />
              <span>秒</span>
            </template>
          </div>
          <span class="sync-status-pill">{{ syncStatusText }}</span>
        </div>
      </section>
    </div>

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
      <NEmpty description="还没有自定义板块" size="small" />
    </div>

    <CustomSectorEditModal
      v-model:show="editOpen"
      :sector="editingSector"
      @updated="onSectorUpdated"
    />
  </div>
</template>

<style scoped src="./settingsOverview.css"></style>
