<script setup lang="ts">
import { NCard, NStatistic } from 'naive-ui'
import { onMounted, ref } from 'vue'

import AsyncPanel from '@/components/workbench/AsyncPanel.vue'
import { fetchHealthDetail } from '@/api/replay'

const health = ref<Awaited<ReturnType<typeof fetchHealthDetail>> | null>(null)
const error = ref('')

function collectorLabel(): string {
  if (!health.value) return '-'
  return health.value.collector_online ? '在线' : '离线'
}

function roleLabel(role: string): string {
  const info = health.value?.collector_roles?.[role]
  if (!info) return '未启动'
  return info.online ? '在线' : '离线'
}

async function load() {
  error.value = ''
  try {
    health.value = await fetchHealthDetail()
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : String(loadError)
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-grid">
    <NCard title="数据健康" size="small">
      <AsyncPanel :error="error">
        <div v-if="health" class="stat-grid">
          <NStatistic label="目录版本" :value="health.catalog_version ?? '-'" />
          <NStatistic label="未解决 Gap" :value="health.unresolved_gaps" />
          <NStatistic label="覆盖率" :value="health.coverage_pct ?? '-'" />
          <NStatistic label="采集器" :value="collectorLabel()" />
          <NStatistic label="Hot 采集" :value="roleLabel('hot')" />
          <NStatistic label="Archive 采集" :value="roleLabel('archive')" />
        </div>
      </AsyncPanel>
    </NCard>
    <NCard title="说明" size="small">
      <p class="hint">
        健康页展示采集与目录状态（只读）。通达信目录、采集范围、保留策略请在「设置」页修改。
      </p>
    </NCard>
  </div>
</template>

<style scoped>
.page-grid {
  display: grid;
  gap: 16px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.hint {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
}
</style>
