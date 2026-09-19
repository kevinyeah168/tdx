<script setup lang="ts">

import {

  NAlert,

  NButton,

  NCard,

  NInputNumber,

  NSpace,

} from 'naive-ui'

import { computed, onMounted, ref } from 'vue'



import AsyncPanel from '@/components/workbench/AsyncPanel.vue'

import SettingsCustomSectors from '@/components/workbench/SettingsCustomSectors.vue'

import SettingsGroupsPanel from '@/components/workbench/SettingsGroupsPanel.vue'

import { fetchReplayDates } from '@/api/replay'

import {

  fetchSettingsDetail,

  updateSettingsDetail,

  type SettingsDetail,

} from '@/api/settings'



const MB_PER_TRADING_DAY = 650

const TRADING_DAYS_PER_YEAR = 250



const loading = ref(false)

const saving = ref(false)

const error = ref('')

const message = ref('')



const settings = ref<SettingsDetail | null>(null)

const retentionDays = ref(365)

const storedDayCount = ref(0)



const storedSizeGb = computed(() =>

  Math.round((storedDayCount.value * MB_PER_TRADING_DAY) / 1024 * 10) / 10,

)

const retentionEstimateGb = computed(() =>

  Math.round((retentionDays.value / 365) * TRADING_DAYS_PER_YEAR * MB_PER_TRADING_DAY / 1024),

)



async function loadCore() {

  loading.value = true

  error.value = ''

  try {

    const [detail, dates] = await Promise.all([

      fetchSettingsDetail(),

      fetchReplayDates().catch(() => ({ dates: [] })),

    ])

    settings.value = detail

    retentionDays.value = detail.retention_days

    storedDayCount.value = dates.dates.length

  } catch (loadError) {

    error.value = loadError instanceof Error ? loadError.message : String(loadError)

  } finally {

    loading.value = false

  }

}



async function saveRetention() {

  saving.value = true

  message.value = ''

  error.value = ''

  try {

    settings.value = await updateSettingsDetail({ retention_days: retentionDays.value })

    message.value = '数据保留策略已保存。'

  } catch (saveError) {

    error.value = saveError instanceof Error ? saveError.message : String(saveError)

  } finally {

    saving.value = false

  }

}



onMounted(() => {

  void loadCore()

})

</script>



<template>

  <div class="settings-page">

    <AsyncPanel :loading="loading" :error="error">

      <NAlert v-if="message" type="success" class="banner" :title="message" />



      <div class="page-grid">

        <div class="settings-split">

          <NCard class="panel split-panel" title="分组管理" size="small">

            <SettingsGroupsPanel />

          </NCard>

          <NCard class="panel split-panel" title="自定义板块" size="small">

            <SettingsCustomSectors />

          </NCard>

        </div>



        <NCard class="panel panel-wide storage-panel" title="数据存储" size="small">

          <p class="hint mb-3">

            每个交易日约 <strong>{{ MB_PER_TRADING_DAY }} MB</strong>（全市场分钟库）。

            当前已存约 <strong>{{ storedSizeGb }} GB</strong>（{{ storedDayCount }} 个交易日）。

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

            <span class="hint">此项不常修改，变更后需保存才会生效。</span>

            <NButton type="primary" :loading="saving" @click="saveRetention">保存保留策略</NButton>

          </div>

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

  margin-bottom: 12px;

}



.page-grid {

  display: grid;

  gap: 12px;

}



.settings-split {

  display: grid;

  grid-template-columns: repeat(2, minmax(0, 1fr));

  gap: 12px;

  align-items: stretch;

  min-height: min(72vh, 640px);

}



.split-panel {

  display: flex;

  flex-direction: column;

  min-height: 0;

  min-width: 0;

  overflow: hidden;

}



.split-panel :deep(.n-card__content) {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 0 16px 16px !important;
}



.panel-wide {

  grid-column: 1 / -1;

}



.storage-panel {

  margin-top: 4px;

}



.panel :deep(.n-card-header) {
  padding: 14px 16px 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
}

.panel :deep(.n-card-header__main) {
  font-size: 14px;
  font-weight: 600;
}

.split-panel :deep(.n-card-header) {
  padding: 16px 16px 0 !important;
  border-bottom: none !important;
  background: transparent;
}

.split-panel :deep(.n-card__content > *) {
  padding-top: 16px;
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



.mt-2 {

  margin-top: 8px;

}



.mb-3 {

  margin-bottom: 12px;

}



@media (max-width: 1100px) {

  .settings-split {

    grid-template-columns: 1fr;

    min-height: 0;

  }

}

</style>


