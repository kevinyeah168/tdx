<script setup lang="ts">
import { NButton, NInput } from 'naive-ui'
import { computed, ref } from 'vue'

import SettingsSectorGroups from '@/components/workbench/SettingsSectorGroups.vue'
import SettingsStockGroups from '@/components/workbench/SettingsStockGroups.vue'

const emit = defineEmits<{
  changed: []
}>()

const activeTab = ref<'sector' | 'stock'>('sector')
const newName = ref('')
const creating = ref(false)
const error = ref('')

const sectorPanel = ref<InstanceType<typeof SettingsSectorGroups> | null>(null)
const stockPanel = ref<InstanceType<typeof SettingsStockGroups> | null>(null)

const createPlaceholder = computed(() =>
  activeTab.value === 'sector' ? '新板块分组名称' : '新个股分组名称',
)

const toolbarMeta = computed(() =>
  activeTab.value === 'sector'
    ? '每组最多 60 板块 · 曲线 60 条'
    : '每组最多 50 只个股',
)

async function handleCreate() {
  const name = newName.value.trim()
  if (!name) return
  creating.value = true
  error.value = ''
  try {
    if (activeTab.value === 'sector') {
      await sectorPanel.value?.createGroup(name)
    } else {
      await stockPanel.value?.createGroup(name)
    }
    newName.value = ''
    emit('changed')
  } catch (createError) {
    error.value = createError instanceof Error ? createError.message : String(createError)
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div class="groups-shell">
    <div class="settings-panel-toolbar">
      <div class="segmented-control" role="tablist" aria-label="分组类型">
        <button
          type="button"
          role="tab"
          :aria-selected="activeTab === 'sector'"
          :class="{ active: activeTab === 'sector' }"
          @click="activeTab = 'sector'"
        >
          板块分组
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="activeTab === 'stock'"
          :class="{ active: activeTab === 'stock' }"
          @click="activeTab = 'stock'"
        >
          个股分组
        </button>
      </div>

      <div class="toolbar-create">
        <span class="toolbar-meta">{{ toolbarMeta }}</span>
        <NInput
          v-model:value="newName"
          size="small"
          class="create-input"
          :placeholder="createPlaceholder"
          @keyup.enter="handleCreate"
        />
        <NButton size="small" type="primary" :loading="creating" @click="handleCreate">
          创建分组
        </NButton>
      </div>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <SettingsSectorGroups
      v-show="activeTab === 'sector'"
      ref="sectorPanel"
      class="tab-panel"
      @changed="emit('changed')"
    />
    <SettingsStockGroups
      v-show="activeTab === 'stock'"
      ref="stockPanel"
      class="tab-panel"
      @changed="emit('changed')"
    />
  </div>
</template>

<style scoped src="./settingsOverview.css"></style>
<style scoped>
.groups-shell {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow: hidden;
  box-sizing: border-box;
}

.error-text {
  margin: 0;
  font-size: 12px;
  color: var(--danger, #dc2626);
}

.tab-panel {
  flex: 1;
  min-height: 0;
}
</style>
