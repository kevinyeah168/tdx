<script setup lang="ts">
import { NButton, NCard, NStatistic, NTag } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'

import AsyncPanel from '@/components/workbench/AsyncPanel.vue'
import { fetchMarketOverview } from '@/api/market'
import { fetchHealthDetail, fetchReplayDates } from '@/api/replay'
import {
  fetchSettingsAuditLog,
  fetchSettingsDetail,
  restartCollectors,
  type SettingsDetail,
} from '@/api/settings'

const MB_PER_TRADING_DAY = 650

const health = ref<Awaited<ReturnType<typeof fetchHealthDetail>> | null>(null)
const settings = ref<SettingsDetail | null>(null)
const error = ref('')
const message = ref('')
const restarting = ref(false)
const auditLoading = ref(false)
const auditItems = ref<Array<Record<string, unknown>>>([])

const storedDayCount = ref(0)
const catalogSectorCount = ref(0)
const catalogStockCount = ref(0)

const storedSizeGb = computed(() =>
  Math.round((storedDayCount.value * MB_PER_TRADING_DAY) / 1024 * 10) / 10,
)
const tdxProbeOk = computed(() => settings.value?.tdx_probe?.ok ?? null)
const collectorOnline = computed(() => Boolean(health.value?.collector_online))
const collectorLastSeen = computed(() => health.value?.collector_last_seen ?? null)

function collectorLabel(): string {
  if (!health.value) return '-'
  return health.value.collector_online ? '在线' : '离线'
}

function probeLabel(ok: boolean | null): string {
  if (ok === null) return '未检测'
  return ok ? '正常' : '异常'
}

async function load() {
  error.value = ''
  try {
    const today = new Date().toISOString().slice(0, 10)
    const [healthDetail, detail, dates, overview] = await Promise.all([
      fetchHealthDetail(),
      fetchSettingsDetail(true).catch(() => null),
      fetchReplayDates().catch(() => ({ dates: [] })),
      fetchMarketOverview(today).catch(() => null),
    ])
    health.value = healthDetail
    settings.value = detail
    storedDayCount.value = dates.dates.length
    if (overview) {
      catalogSectorCount.value = overview.sector_count
      catalogStockCount.value = overview.security_count
    }
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : String(loadError)
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

async function restartCollectorProcesses() {
  restarting.value = true
  message.value = ''
  error.value = ''
  try {
    await restartCollectors()
    message.value = '采集器已重启，请稍候刷新状态。'
    void loadAudit()
    await load()
  } catch (restartError) {
    error.value = restartError instanceof Error ? restartError.message : String(restartError)
  } finally {
    restarting.value = false
  }
}

onMounted(async () => {
  await load()
  void loadAudit()
})
</script>

<template>
  <div class="health-page">
    <AsyncPanel :error="error">
      <p v-if="message" class="banner success">{{ message }}</p>

      <div class="page-grid">
        <NCard title="数据健康" size="small" class="panel">
          <div v-if="health" class="stat-grid">
            <NStatistic label="目录版本" :value="health.catalog_version ?? '-'" />
            <NStatistic label="未解决 Gap" :value="health.unresolved_gaps" />
            <NStatistic label="覆盖率" :value="health.coverage_pct ?? '-'" />
            <NStatistic label="采集器" :value="collectorLabel()" />
            <NStatistic label="已存交易日" :value="storedDayCount" />
            <NStatistic label="磁盘估算" :value="`${storedSizeGb} GB`" />
          </div>
          <p v-else class="hint">加载中…</p>
        </NCard>

        <NCard title="数据采集" size="small" class="panel">
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
            <NTag :type="collectorOnline ? 'success' : 'default'" size="small">
              采集{{ collectorOnline ? '在线' : '离线' }}
            </NTag>
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

        <NCard class="panel panel-wide" title="最近变更" size="small">
          <div v-if="auditLoading" class="hint">加载变更记录…</div>
          <ul v-else-if="auditItems.length" class="audit-list">
            <li v-for="(item, index) in auditItems" :key="index">
              {{ item.at }} — {{ item.action }}
            </li>
          </ul>
          <p v-else class="hint">暂无变更记录。</p>
        </NCard>

        <NCard title="说明" size="small" class="panel panel-wide">
          <p class="hint">
            健康页展示采集、目录与运行状态（只读）。板块分组、自定义板块与数据保留请在「设置」页修改。
          </p>
        </NCard>
      </div>
    </AsyncPanel>
  </div>
</template>

<style scoped>
.health-page {
  overflow: auto;
  padding: 4px 4px 20px;
}

.page-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.panel-wide {
  grid-column: 1 / -1;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
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

.audit-list {
  margin: 0;
  padding-left: 18px;
  max-height: 280px;
  overflow-y: auto;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

.banner {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
}

.banner.success {
  color: var(--text);
  background: color-mix(in srgb, #16a34a 12%, var(--panel));
  border: 1px solid color-mix(in srgb, #16a34a 30%, var(--border));
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

@media (max-width: 960px) {
  .page-grid {
    grid-template-columns: 1fr;
  }

  .panel-wide {
    grid-column: auto;
  }

  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
