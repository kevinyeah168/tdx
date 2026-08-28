<script setup lang="ts">
import { MoonOutline, RefreshOutline, SunnyOutline } from '@vicons/ionicons5'
import { NButton, NDropdown, NIcon, NTag, NTooltip } from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'

import GlobalSearch from '@/components/workbench/GlobalSearch.vue'
import PrimaryNav from '@/components/workbench/PrimaryNav.vue'
import PulseHomePage from '@/components/workbench/PulseHomePage.vue'
import ReplayControls from '@/components/workbench/ReplayControls.vue'
import SectorWorkspace from '@/components/workbench/SectorWorkspace.vue'
import HealthPage from '@/components/workbench/HealthPage.vue'
import SettingsPage from '@/components/workbench/SettingsPage.vue'
import StockWorkspace from '@/components/workbench/StockWorkspace.vue'
import { useBoardStore } from '@/stores/boardStore'
import { useMarketStore } from '@/stores/marketStore'
import { useReplayStore } from '@/stores/replayStore'
import { useSectorStore } from '@/stores/sectorStore'
import { useThemeStore, type ThemeMode } from '@/stores/themeStore'
import { fmtPct } from '@/utils/format'

const marketStore = useMarketStore()
const sectorStore = useSectorStore()
const boardStore = useBoardStore()
const replayStore = useReplayStore()
const themeStore = useThemeStore()

const activeView = ref<'home' | 'sectors' | 'stock' | 'health' | 'settings'>('home')
const selectedStock = ref('')
const refreshing = ref(false)
const bootstrapped = ref(false)

const themeLabel = computed(() => {
  if (themeStore.mode === 'system') return '跟随系统'
  return themeStore.isDark ? '深色' : '浅色'
})

const themeOptions = [
  { label: '浅色', key: 'light' },
  { label: '深色', key: 'dark' },
  { label: '跟随系统', key: 'system' },
]

const themeIcon = computed(() => (themeStore.isDark ? MoonOutline : SunnyOutline))

const coverageLabel = computed(() => {
  const pct = marketStore.overview?.metadata.coverage_pct
  if (pct == null) return null
  return `覆盖率 ${fmtPct(pct).replace('+', '')}`
})

function onSearch(symbol: string) {
  selectedStock.value = symbol
  activeView.value = 'stock'
}

function onOpenStock(symbol: string) {
  selectedStock.value = symbol
  activeView.value = 'stock'
}

async function refreshAll() {
  refreshing.value = true
  try {
    await marketStore.loadOverview()
    if (activeView.value === 'home') {
      await boardStore.manualRefresh()
    } else {
      await sectorStore.reloadForDate()
      replayStore.minute = sectorStore.replayMinute
    }
  } finally {
    refreshing.value = false
  }
}

watch(
  () => [replayStore.tradeDate, replayStore.minute] as const,
  ([tradeDate, minute]) => {
    if (!bootstrapped.value) return
    sectorStore.setTradeDate(tradeDate, minute)
    marketStore.tradeDate = tradeDate
    void marketStore.loadOverview()
  },
)

onMounted(async () => {
  await replayStore.loadAvailableDates()
  await sectorStore.bootstrap()
  replayStore.tradeDate = sectorStore.tradeDate
  replayStore.minute = sectorStore.replayMinute
  marketStore.tradeDate = sectorStore.tradeDate
  bootstrapped.value = true
  await marketStore.loadOverview()
})
</script>

<template>
  <div class="workbench-shell">
    <header class="panel-card header-bar">
      <div class="header-left">
        <h1 class="header-title">TDX Market Workbench</h1>
        <NTag v-if="marketStore.overview" size="small" type="success" :bordered="false">
          A股 {{ marketStore.overview.security_count }}
        </NTag>
        <NTag v-if="marketStore.overview" size="small" :bordered="false">
          板块 {{ marketStore.overview.sector_count }}
        </NTag>
        <NTag v-if="coverageLabel" size="small" type="warning" :bordered="false">{{ coverageLabel }}</NTag>
        <span class="header-divider" />
        <PrimaryNav v-model="activeView" />
      </div>

      <div class="header-right">
        <ReplayControls />
        <GlobalSearch @select="onSearch" />
        <NDropdown trigger="click" :options="themeOptions" @select="(k) => themeStore.setMode(k as ThemeMode)">
          <NTooltip>
            <template #trigger>
              <NButton quaternary circle size="small">
                <template #icon>
                  <NIcon :component="themeIcon" />
                </template>
              </NButton>
            </template>
            主题：{{ themeLabel }}
          </NTooltip>
        </NDropdown>
        <NButton type="primary" size="small" :loading="refreshing" @click="refreshAll">
          <template #icon>
            <NIcon :component="RefreshOutline" />
          </template>
          刷新
        </NButton>
      </div>
    </header>

    <main class="workbench-main">
      <PulseHomePage v-if="activeView === 'home'" />

      <SectorWorkspace v-else-if="activeView === 'sectors'" @open-stock="onOpenStock" />

      <StockWorkspace
        v-else-if="activeView === 'stock' && selectedStock"
        :symbol="selectedStock"
        @back="activeView = 'sectors'"
      />
      <div v-else-if="activeView === 'stock'" class="panel-card empty-hint">
        请从板块成分股或顶部搜索选择个股
      </div>

      <HealthPage v-else-if="activeView === 'health'" />
      <SettingsPage v-else-if="activeView === 'settings'" />
    </main>

    <p v-if="marketStore.error || sectorStore.error || sectorStore.fundError || boardStore.board.error" class="workbench-error">
      {{ marketStore.error || sectorStore.error || sectorStore.fundError || boardStore.board.error }}
    </p>
  </div>
</template>

<style scoped>
.workbench-shell {
  display: flex;
  height: 100vh;
  flex-direction: column;
  gap: 6px;
  padding: 6px;
  overflow: hidden;
  box-sizing: border-box;
}

.header-bar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: 44px;
  padding: 0 12px;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.header-left {
  flex: 1;
}

.header-right {
  flex-shrink: 0;
}

.header-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  letter-spacing: -0.01em;
}

.header-divider {
  width: 1px;
  height: 18px;
  background: var(--border);
  flex-shrink: 0;
}

.workbench-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.empty-hint {
  padding: 3rem;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

.workbench-error {
  flex-shrink: 0;
  margin: 0;
  padding: 0 4px;
  font-size: 12px;
  color: #ef4444;
}

@media (max-width: 1200px) {
  .header-bar {
    height: auto;
    min-height: 44px;
    flex-wrap: wrap;
    padding: 6px 12px;
    row-gap: 6px;
  }

  .header-right {
    width: 100%;
    justify-content: flex-end;
    flex-wrap: wrap;
  }
}
</style>
