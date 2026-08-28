<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NDataTable,
  NInput,
  NInputNumber,
  NRadio,
  NRadioGroup,
  NSelect,
  NSpace,
  NTag,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { computed, h, onMounted, ref, watch } from 'vue'

import AsyncPanel from '@/components/workbench/AsyncPanel.vue'
import {
  fetchCollectionTargets,
  fetchSettingsAuditLog,
  fetchSettingsDetail,
  probeTdxHome,
  restartCollectors,
  saveCollectionTargets,
  updateSettingsDetail,
  type SettingsDetail,
  type TdxProbeResult,
} from '@/api/settings'
import { fetchSectorCatalogMembers, fetchSectorRank, fetchSectors } from '@/api/sectors'

interface StockRow {
  symbol: string
  name: string
  sectors: string[]
  checked: boolean
}

const loading = ref(false)
const saving = ref(false)
const probing = ref(false)
const restarting = ref(false)
const error = ref('')
const message = ref('')

const settings = ref<SettingsDetail | null>(null)
const retentionDays = ref(30)
const tdxHome = ref('C:/new_tdx64')
const collectMode = ref<'selective' | 'full'>('selective')
const archiveFullEnabled = ref(false)
const probeResult = ref<TdxProbeResult | null>(null)

const sectorOptions = ref<Array<{ label: string; value: string }>>([])
const selectedSectorIds = ref<string[]>([])
const stockRows = ref<StockRow[]>([])
const auditItems = ref<Array<Record<string, unknown>>>([])

const maxSectors = computed(() => settings.value?.priority_max_sectors ?? 80)
const maxStocks = computed(() => settings.value?.priority_max_stocks ?? 1000)
const sectorMemberLimit = computed(() => settings.value?.priority_sector_members ?? 30)

const selectedStockCount = computed(() => stockRows.value.filter((row) => row.checked).length)

const stockColumns: DataTableColumns<StockRow> = [
  {
    title: '采集',
    key: 'checked',
    width: 64,
    render: (row) =>
      h(NCheckbox, {
        checked: row.checked,
        onUpdateChecked: (value: boolean) => {
          row.checked = value
        },
      }),
  },
  { title: '代码', key: 'symbol', width: 100 },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '所属板块',
    key: 'sectors',
    render: (row) =>
      h(
        NSpace,
        { size: 4 },
        {
          default: () =>
            row.sectors.slice(0, 3).map((sectorId) =>
              h(NTag, { size: 'small', bordered: false }, { default: () => sectorId }),
            ),
        },
      ),
  },
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [detailResult, targetsResult, sectorsResult, auditResult] = await Promise.allSettled([
      fetchSettingsDetail(),
      fetchCollectionTargets(),
      fetchSectors(),
      fetchSettingsAuditLog(),
    ])

    if (detailResult.status === 'rejected') {
      throw detailResult.reason
    }
    const detail = detailResult.value
    settings.value = detail
    retentionDays.value = detail.retention_days
    tdxHome.value = detail.tdx_home
    collectMode.value = detail.collect_mode
    archiveFullEnabled.value = detail.archive_full_enabled
    probeResult.value = detail.tdx_probe
      ? {
          tdx_home: detail.tdx_home,
          vipdoc_ok: detail.tdx_probe.vipdoc_ok,
          tnf_ok: detail.tdx_probe.tnf_ok,
          mac_reachable: detail.tdx_probe.mac_reachable,
          client_likely_running: detail.tdx_probe.client_likely_running,
          ok: detail.tdx_probe.ok,
          mac_port: 0,
        }
      : null

    if (targetsResult.status === 'fulfilled') {
      selectedSectorIds.value = [...targetsResult.value.sector_ids]
      await rebuildStockRows(targetsResult.value.symbols)
    } else {
      error.value =
        '采集目标接口不可用，请执行 stop-workbench-all.cmd 后重新 start-workbench-all-background.cmd 重启 API。'
    }

    if (sectorsResult.status === 'fulfilled') {
      sectorOptions.value = sectorsResult.value.items.map((item) => ({
        label: `${item.name} (${item.sector_id})`,
        value: item.sector_id,
      }))
    }

    if (auditResult.status === 'fulfilled') {
      auditItems.value = auditResult.value.items
    }
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : String(loadError)
  } finally {
    loading.value = false
  }
}

async function rebuildStockRows(preselected: string[] = []) {
  const selectedSet = new Set(preselected.map((s) => s.toUpperCase()))
  const bySymbol = new Map<string, StockRow>()

  for (const sectorId of selectedSectorIds.value) {
    try {
      const response = await fetchSectorCatalogMembers(sectorId)
      for (const item of response.items) {
        const existing = bySymbol.get(item.symbol)
        if (existing) {
          if (!existing.sectors.includes(sectorId)) existing.sectors.push(sectorId)
          continue
        }
        bySymbol.set(item.symbol, {
          symbol: item.symbol,
          name: item.name,
          sectors: [sectorId],
          checked: selectedSet.size === 0 || selectedSet.has(item.symbol),
        })
      }
    } catch {
      // skip sectors that fail to load
    }
  }

  for (const symbol of preselected) {
    const normalized = symbol.toUpperCase()
    if (!bySymbol.has(normalized)) {
      bySymbol.set(normalized, {
        symbol: normalized,
        name: normalized,
        sectors: [],
        checked: true,
      })
    } else {
      bySymbol.get(normalized)!.checked = true
    }
  }

  stockRows.value = Array.from(bySymbol.values()).sort((a, b) => a.symbol.localeCompare(b.symbol))
}

watch(selectedSectorIds, () => {
  void rebuildStockRows(stockRows.value.filter((row) => row.checked).map((row) => row.symbol))
})

async function runProbe() {
  probing.value = true
  message.value = ''
  try {
    probeResult.value = await probeTdxHome(tdxHome.value)
  } catch (probeError) {
    error.value = probeError instanceof Error ? probeError.message : String(probeError)
  } finally {
    probing.value = false
  }
}

async function saveGeneralSettings() {
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    settings.value = await updateSettingsDetail({
      retention_days: retentionDays.value,
      tdx_home: tdxHome.value,
      collect_mode: collectMode.value,
      archive_full_enabled: archiveFullEnabled.value,
    })
    message.value = '通用设置已保存。修改通达信目录或采集模式后建议重启采集器。'
    const audit = await fetchSettingsAuditLog()
    auditItems.value = audit.items
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function saveCollection() {
  saving.value = true
  message.value = ''
  error.value = ''
  const sectorIds = selectedSectorIds.value.slice(0, maxSectors.value)
  const symbols = stockRows.value.filter((row) => row.checked).map((row) => row.symbol).slice(0, maxStocks.value)
  try {
    await saveCollectionTargets({ sector_ids: sectorIds, symbols })
    message.value = `采集目标已保存：${sectorIds.length} 板块，手动个股 ${symbols.length} 只；Hot 将按每板块 Top ${sectorMemberLimit.value} 成分股自动展开（总上限 ${maxStocks.value}）。`
    const audit = await fetchSettingsAuditLog()
    auditItems.value = audit.items
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function importRankSectors() {
  const today = new Date().toISOString().slice(0, 10)
  try {
    const rank = await fetchSectorRank(today, null, 20)
    const merged = new Set([...selectedSectorIds.value, ...rank.items.map((item) => item.sector_id)])
    selectedSectorIds.value = Array.from(merged).slice(0, maxSectors.value)
  } catch (importError) {
    error.value = importError instanceof Error ? importError.message : String(importError)
  }
}

function selectAllStocks() {
  stockRows.value.forEach((row) => {
    row.checked = true
  })
}

function clearStocks() {
  stockRows.value.forEach((row) => {
    row.checked = false
  })
}

async function restartCollectorProcesses() {
  restarting.value = true
  message.value = ''
  try {
    await restartCollectors()
    message.value = '采集器已重启，请稍后在健康页确认状态。'
    const audit = await fetchSettingsAuditLog()
    auditItems.value = audit.items
  } catch (restartError) {
    error.value = restartError instanceof Error ? restartError.message : String(restartError)
  } finally {
    restarting.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="settings-page">
    <AsyncPanel :loading="loading" :error="error">
      <NAlert v-if="message" type="success" class="mb-3" :title="message" />

      <div class="page-grid">
        <NCard title="通达信数据源" size="small">
          <NSpace vertical :size="12">
            <div class="field-row">
              <label class="field-label">安装目录</label>
              <NInput v-model:value="tdxHome" placeholder="例如 C:\new_tdx64" />
              <NButton :loading="probing" @click="runProbe">检测</NButton>
            </div>
            <div v-if="probeResult" class="probe-tags">
              <NTag :type="probeResult.vipdoc_ok ? 'success' : 'error'" size="small">vipdoc</NTag>
              <NTag :type="probeResult.tnf_ok ? 'success' : 'warning'" size="small">名称缓存</NTag>
              <NTag :type="probeResult.mac_reachable ? 'success' : 'error'" size="small">MAC 端口</NTag>
              <NTag :type="probeResult.client_likely_running ? 'success' : 'warning'" size="small">
                客户端{{ probeResult.client_likely_running ? '已连接' : '未检测到' }}
              </NTag>
            </div>
            <p class="hint">
              板块主力与成分股排行依赖 MAC 接口，通常需要通达信客户端运行。本地日 K 与名称缓存只需目录正确。
            </p>
          </NSpace>
        </NCard>

        <NCard title="采集策略" size="small">
          <NRadioGroup v-model:value="collectMode">
            <NSpace vertical>
              <NRadio value="selective">精选采集（推荐）— 仅采集选定板块与个股</NRadio>
              <NRadio value="full">全量采集 — Archive 在非交易时段回补全市场</NRadio>
            </NSpace>
          </NRadioGroup>
          <NAlert
            v-if="collectMode === 'full'"
            type="warning"
            class="mt-3"
            title="风险提示"
          >
            全量回补单次可达数分钟。盘中 Hot 仍只跑精选目标；Archive 在午休/收盘后执行全量。
          </NAlert>
          <div v-if="collectMode === 'full'" class="mt-3">
            <NCheckbox v-model:checked="archiveFullEnabled">启用 Archive 全量回补（5216 股级）</NCheckbox>
          </div>
        </NCard>

        <NCard title="精选采集目标" size="small">
          <NSpace class="mb-3" :size="8">
            <NButton size="small" @click="importRankSectors">从榜单 Top20 导入</NButton>
            <NButton size="small" @click="selectAllStocks">全选个股</NButton>
            <NButton size="small" @click="clearStocks">清空个股</NButton>
          </NSpace>
          <div class="field-row mb-3">
            <label class="field-label">板块（最多 {{ maxSectors }}）</label>
            <NSelect
              v-model:value="selectedSectorIds"
              multiple
              filterable
              clearable
              :options="sectorOptions"
              placeholder="搜索并选择板块"
              max-tag-count="responsive"
            />
          </div>
          <p class="hint mb-2">
            已选 {{ selectedSectorIds.length }} 板块；保存后 Hot 自动采集每板块主力 Top
            {{ sectorMemberLimit }} 成分股（联动板块 Top {{ settings?.priority_linkage_members ?? 30 }}），总上限
            {{ maxStocks }}。下方表格为额外手动勾选个股（{{ selectedStockCount }}）。
          </p>
          <NDataTable
            :columns="stockColumns"
            :data="stockRows"
            :max-height="320"
            size="small"
            :bordered="false"
          />
          <NSpace class="mt-3">
            <NButton type="primary" :loading="saving" @click="saveCollection">保存采集目标</NButton>
          </NSpace>
        </NCard>

        <NCard title="保留策略" size="small">
          <NSpace align="center">
            <NInputNumber v-model:value="retentionDays" :min="1" :max="2500" />
            <NButton type="primary" :loading="saving" @click="saveGeneralSettings">保存设置</NButton>
            <NButton :loading="restarting" @click="restartCollectorProcesses">重启采集器</NButton>
          </NSpace>
          <p class="hint mt-2">默认 30 个交易日，Collector 下一轮清理生效。</p>
        </NCard>

        <NCard v-if="auditItems.length" title="最近变更" size="small">
          <ul class="audit-list">
            <li v-for="(item, index) in auditItems" :key="index">
              {{ item.at }} — {{ item.action }}
            </li>
          </ul>
        </NCard>
      </div>
    </AsyncPanel>
  </div>
</template>

<style scoped>
.settings-page {
  overflow: auto;
  padding-bottom: 16px;
}

.page-grid {
  display: grid;
  gap: 16px;
}

.field-row {
  display: grid;
  grid-template-columns: 100px 1fr auto;
  gap: 8px;
  align-items: center;
}

.field-label {
  font-size: 13px;
  color: var(--muted);
}

.probe-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.audit-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--muted);
}

.mb-2 {
  margin-bottom: 8px;
}

.mb-3 {
  margin-bottom: 12px;
}

.mt-2 {
  margin-top: 8px;
}

.mt-3 {
  margin-top: 12px;
}
</style>
