<script setup lang="ts">
import {
  NAlert,
  NButton,
  NCard,
  NInputNumber,
  NSpace,
  NStatistic,
  NTag,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'

import AsyncPanel from '@/components/workbench/AsyncPanel.vue'
import SettingsSectorGroups from '@/components/workbench/SettingsSectorGroups.vue'
import SettingsStockGroups from '@/components/workbench/SettingsStockGroups.vue'
import { fetchMarketOverview } from '@/api/market'
import { fetchHealthDetail, fetchReplayDates } from '@/api/replay'
import { fetchSectorGroups } from '@/api/sectorGroups'
import {
  fetchSettingsAuditLog,
  fetchSettingsDetail,
  restartCollectors,
  updateSettingsDetail,
  type SettingsDetail,
} from '@/api/settings'

const MB_PER_TRADING_DAY = 650
const TRADING_DAYS_PER_YEAR = 250

const loading = ref(false)
const saving = ref(false)
const restarting = ref(false)
const auditLoading = ref(false)
const error = ref('')
const message = ref('')

const settings = ref<SettingsDetail | null>(null)
const retentionDays = ref(365)
const auditItems = ref<Array<Record<string, unknown>>>([])

const storedDayCount = ref(0)
const groupCount = ref(0)
const activeGroupMemberCount = ref(0)
const catalogSectorCount = ref(0)
const catalogStockCount = ref(0)
const collectorOnline = ref(false)
const collectorLastSeen = ref<string | null>(null)

const storedSizeGb = computed(() =>
  Math.round((storedDayCount.value * MB_PER_TRADING_DAY) / 1024 * 10) / 10,
)
const retentionEstimateGb = computed(() =>
  Math.round((retentionDays.value / 365) * TRADING_DAYS_PER_YEAR * MB_PER_TRADING_DAY / 1024),
)
const tdxProbeOk = computed(() => settings.value?.tdx_probe?.ok ?? null)

function probeLabel(ok: boolean | null): string {
  if (ok === null) return '未检测'
  return ok ? '正常' : '异常'
}

async function loadCore() {
  loading.value = true
  error.value = ''
  try {
    const today = new Date().toISOString().slice(0, 10)
    const [detail, groups, dates, health, overview] = await Promise.all([
      fetchSettingsDetail(true),
      fetchSectorGroups().catch(() => ({ items: [], active_group_id: '' })),
      fetchReplayDates().catch(() => ({ dates: [] })),
      fetchHealthDetail().catch(() => null),
      fetchMarketOverview(today).catch(() => null),
    ])

    settings.value = detail
    retentionDays.value = detail.retention_days

    groupCount.value = groups.items.length
    const activeGroup =
      groups.items.find((group) => group.id === groups.active_group_id) ?? groups.items[0]
    activeGroupMemberCount.value = activeGroup?.sectors.length ?? 0

    storedDayCount.value = dates.dates.length
    collectorOnline.value = Boolean(health?.collector_online)
    collectorLastSeen.value = health?.collector_last_seen ?? null

    if (overview) {
      catalogSectorCount.value = overview.sector_count
      catalogStockCount.value = overview.security_count
    }
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : String(loadError)
  } finally {
    loading.value = false
  }
}

async function loadAudit() {
  auditLoading.value = true
  try {
    const audit = await fetchSettingsAuditLog()
    auditItems.value = audit.items
  } catch {
    auditItems.value = []
  } finally {
    auditLoading.value = false
  }
}

async function saveRetention() {
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    settings.value = await updateSettingsDetail({ retention_days: retentionDays.value })
    message.value = '数据保留策略已保存。'
    void loadAudit()
  } catch (saveError) {
    error.value = saveError instanceof Error ? saveError.message : String(saveError)
  } finally {
    saving.value = false
  }
}

async function restartCollectorProcesses() {
  restarting.value = true
  message.value = ''
  try {
    await restartCollectors()
    message.value = '采集器已重启，请稍后在健康页确认状态。'
    void loadAudit()
    void loadCore()
  } catch (restartError) {
    error.value = restartError instanceof Error ? restartError.message : String(restartError)
  } finally {
    restarting.value = false
  }
}

function onGroupsChanged() {
  void loadCore()
}

onMounted(async () => {
  await loadCore()
  void loadAudit()
})
</script>

<template>
  <div class="settings-page">
    <AsyncPanel :loading="loading" :error="error">
      <NAlert v-if="message" type="success" class="banner" :title="message" />

      <div class="hero">
        <div class="hero-main">
          <h2 class="hero-title">Workbench 设置</h2>
          <p class="hero-desc">配置分组展示、数据保留与采集服务（分组不影响采集范围）。</p>
        </div>
        <div class="hero-stats">
          <NStatistic label="板块分组" :value="groupCount" />
          <NStatistic label="当前组" :value="activeGroupMemberCount" />
          <NStatistic label="交易日" :value="storedDayCount" />
          <NTag :type="collectorOnline ? 'success' : 'default'" size="small">
            采集{{ collectorOnline ? '在线' : '离线' }}
          </NTag>
        </div>
      </div>

      <div class="page-grid">
        <NCard class="panel" title="数据采集" size="small">
          <ul class="bullet-list">
            <li>
              <strong>yuntu</strong> 进程：云图 <code>real_hq</code> 约每 18 秒拉取全市场，按分钟写入板块与个股主力。
            </li>
            <li>
              <strong>gray</strong> 独立进程：东财暗盘约每 15 秒一轮，与主盘互不影响。
            </li>
            <li>
              目录快照：
              <template v-if="catalogSectorCount && catalogStockCount">
                {{ catalogSectorCount }} 板块 / {{ catalogStockCount }} 个股
              </template>
              <template v-else>加载中…</template>
            </li>
          </ul>
          <div class="status-row">
            <NTag :type="tdxProbeOk ? 'success' : tdxProbeOk === false ? 'error' : 'default'" size="small">
              通达信目录 {{ probeLabel(tdxProbeOk) }}
            </NTag>
            <span v-if="collectorLastSeen" class="hint">心跳 {{ collectorLastSeen }}</span>
          </div>
          <div class="footer-row">
            <span class="hint">采集异常时可重启服务（不删已有数据）</span>
            <NButton :loading="restarting" @click="restartCollectorProcesses">重启采集器</NButton>
          </div>
        </NCard>

        <NCard class="panel" title="数据存储" size="small">
          <p class="hint mb-3">
            每个交易日约 <strong>{{ MB_PER_TRADING_DAY }} MB</strong>（全市场分钟库）。
            当前已存约 <strong>{{ storedSizeGb }} GB</strong>。
          </p>
          <NSpace align="center" wrap>
            <span class="inline-label">保留</span>
            <NInputNumber v-model:value="retentionDays" :min="1" :max="2500" />
            <span class="hint">自然日（过期自动删 hot 库）</span>
          </NSpace>
          <p class="hint mt-2">
            按当前设置，磁盘占用上限约 <strong>{{ retentionEstimateGb }} GB</strong>
            （按每年约 {{ TRADING_DAYS_PER_YEAR }} 个交易日估算）。
          </p>
          <div class="footer-row">
            <NButton type="primary" :loading="saving" @click="saveRetention">保存保留策略</NButton>
          </div>
        </NCard>

        <div class="groups-row">
          <NCard class="panel group-panel" title="板块分组" size="small">
            <SettingsSectorGroups @changed="onGroupsChanged" />
          </NCard>
          <NCard class="panel group-panel" title="个股分组" size="small">
            <SettingsStockGroups @changed="onGroupsChanged" />
          </NCard>
        </div>

        <NCard v-if="auditItems.length || auditLoading" class="panel panel-wide" title="最近变更" size="small">
          <div v-if="auditLoading" class="hint">加载变更记录…</div>
          <ul v-else class="audit-list">
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
  padding: 4px 4px 20px;
}

.banner {
  margin-bottom: 16px;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  padding: 12px 16px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--accent) 5%, var(--panel));
}

.hero-main {
  min-width: 0;
}

.hero-title {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 600;
}

.hero-desc {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.hero-stats {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 16px;
}

.hero-stats :deep(.n-statistic) {
  text-align: center;
}

.hero-stats :deep(.n-statistic-value) {
  font-size: 18px !important;
}

.hero-stats :deep(.n-statistic-label) {
  font-size: 11px !important;
}

.page-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.groups-row {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-height: min(62vh, 600px);
}

.groups-row .group-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.groups-row .group-panel :deep(.n-card__content) {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}

.group-panel {
  min-width: 0;
}

.panel-wide {
  grid-column: 1 / -1;
}

.panel :deep(.n-card-header) {
  padding-bottom: 8px;
}

.bullet-list {
  margin: 0 0 12px;
  padding-left: 18px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.footer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}

.inline-label {
  font-size: 13px;
  color: var(--muted);
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

.mt-2 {
  margin-top: 8px;
}

@media (max-width: 1100px) {
  .groups-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
  }

  .hero-stats {
    flex-wrap: wrap;
  }

  .page-grid {
    grid-template-columns: 1fr;
  }

  .panel-wide,
  .groups-row {
    grid-column: auto;
  }
}
</style>
