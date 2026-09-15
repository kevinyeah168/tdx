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

const maxSectors = computed(() => settings.value?.priority_max_sectors ?? 500)
const maxStocks = computed(() => settings.value?.priority_max_stocks ?? 30000)

const selectedStockCount = computed(() => stockRows.value.filter((row) => row.checked).length)

const stockColumns: DataTableColumns<StockRow> = [
  {
    title: '关注',
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
    message.value = '通用设置已保存。修改通达信目录后建议重启采集器。'
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
    message.value = `自选展示已保存：${sectorIds.length} 个默认板块，额外关注个股 ${symbols.length} 只。盘中云图仍采集全市场快照，此处仅影响首页/榜单默认展示。`
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
        <NCard title="盘中采集（云图快照）" size="small">
          <NSpace vertical :size="8">
            <p class="hint">
              Hot 每约 18 秒拉取通达信板块云图 <code>real_hq</code> 全量数据，按交易分钟入库：全市场板块 +
              个股主力快照（约 1000+ 板块、5200+ 个股）。同一分钟内多次拉取会覆盖，整分钟失败会写入 GAP 占位。
            </p>
            <p class="hint">
              暗盘仍由东财单独采集（仅个股，约 15 秒）。云图采集不依赖下方自选板块数量，也不需要通达信客户端在线。
            </p>
          </NSpace>
        </NCard>

        <NCard title="通达信目录（Catalog）" size="small">
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
              用于同步板块成分股、证券代码与名称缓存。云图主力数据走 HTTP，不经过 MAC；MAC/客户端状态仅影响旧版回补或本地行情辅助功能。
            </p>
          </NSpace>
        </NCard>

        <NCard title="Archive 回补（可选）" size="small">
          <NRadioGroup v-model:value="collectMode">
            <NSpace vertical>
              <NRadio value="selective">默认 — 非交易时段用云图快照回补缺失分钟</NRadio>
              <NRadio value="full">旧版全量 — Archive 用 MAC 分笔回补全市场（慢，一般不必开）</NRadio>
            </NSpace>
          </NRadioGroup>
          <NAlert
            v-if="collectMode === 'full'"
            type="warning"
            class="mt-3"
            title="不推荐"
          >
            单次可达数分钟，与当前云图快路径重复。仅在需要 MAC 分笔五档曲线时启用。
          </NAlert>
          <div v-if="collectMode === 'full'" class="mt-3">
            <NCheckbox v-model:checked="archiveFullEnabled">启用 Archive MAC 全量回补</NCheckbox>
          </div>
        </NCard>

        <NCard title="自选板块与关注个股（界面）" size="small">
          <NSpace class="mb-3" :size="8">
            <NButton size="small" @click="importRankSectors">从榜单 Top20 导入</NButton>
            <NButton size="small" @click="selectAllStocks">全选个股</NButton>
            <NButton size="small" @click="clearStocks">清空个股</NButton>
          </NSpace>
          <div class="field-row mb-3">
            <label class="field-label">默认板块</label>
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
            已选 {{ selectedSectorIds.length }} / {{ maxSectors }} 个板块，用于首页榜单与联动默认展示；点击板块时联动成分股上限
            {{ settings?.priority_linkage_members ?? 30 }}。下方表格为额外关注个股（{{ selectedStockCount }}），不影响云图全量入库。
          </p>
          <NDataTable
            :columns="stockColumns"
            :data="stockRows"
            :max-height="320"
            size="small"
            :bordered="false"
          />
          <NSpace class="mt-3">
            <NButton type="primary" :loading="saving" @click="saveCollection">保存自选展示</NButton>
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
