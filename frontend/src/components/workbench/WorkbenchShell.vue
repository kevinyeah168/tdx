<script setup lang="ts">
import { MoonOutline, RefreshOutline, SunnyOutline } from '@vicons/ionicons5'
import { NButton, NDropdown, NIcon, NTag, NTooltip } from 'naive-ui'
import { computed, onMounted, ref, watch } from 'vue'

import HotListWorkspace from '@/components/workbench/HotListWorkspace.vue'
import LimitUpLadderWorkspace from '@/components/workbench/LimitUpLadderWorkspace.vue'
import MemberStockFlowModal from '@/components/workbench/MemberStockFlowModal.vue'
import PrimaryNav from '@/components/workbench/PrimaryNav.vue'
import PulseHomePage from '@/components/workbench/PulseHomePage.vue'
import ReplayControls from '@/components/workbench/ReplayControls.vue'
import SectorWorkspace from '@/components/workbench/SectorWorkspace.vue'
import HealthPage from '@/components/workbench/HealthPage.vue'
import SettingsPage from '@/components/workbench/SettingsPage.vue'
import CycleReplayWorkspace from '@/components/workbench/CycleReplayWorkspace.vue'
import StockWorkspace from '@/components/workbench/StockWorkspace.vue'
import { useBoardStore } from '@/stores/boardStore'
import { useHotListStore } from '@/stores/hotListStore'
import { useLimitUpLadderStore } from '@/stores/limitUpLadderStore'
import { useMarketStore } from '@/stores/marketStore'
import { useReplayStore } from '@/stores/replayStore'
import { useSectorStore } from '@/stores/sectorStore'
import { useStockStore } from '@/stores/stockStore'
import { useThemeStore, type ThemeMode } from '@/stores/themeStore'
import { fmtPct } from '@/utils/format'
import { todayTradeDate } from '@/utils/tradeDate'

const hotListStore = useHotListStore()
const limitUpLadderStore = useLimitUpLadderStore()
const marketStore = useMarketStore()
const sectorStore = useSectorStore()
const stockStore = useStockStore()
const boardStore = useBoardStore()
const replayStore = useReplayStore()
const themeStore = useThemeStore()

const activeView = ref<
  | 'home'
  | 'sectors'
  | 'stock'
  | 'hot-list'
  | 'limit-up-ladder'
  | 'cycle-replay'
  | 'health'
  | 'settings'
>('home')
const selectedStock = ref('')
const stockFlowOpen = ref(false)
const stockFlowTarget = ref<{
  symbol: string
  name: string
  changePct?: number | null
  cumMain?: number | null
  cumGray?: number | null
} | null>(null)
const refreshing = ref(false)
const bootstrapped = ref(false)
let boardDateLoadInFlight = false

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

const shellError = computed(() => {
  switch (activeView.value) {
    case 'home':
      return boardStore.board.error || marketStore.error || ''
    case 'stock':
      return stockStore.error || ''
    case 'hot-list':
      return hotListStore.error || ''
    case 'limit-up-ladder':
      return limitUpLadderStore.error || ''
    case 'sectors':
      return sectorStore.error || sectorStore.fundError || ''
    default:
      return marketStore.error || ''
  }
})

function onOpenStock(target: {
  symbol: string
  name: string
  changePct?: number | null
  cumMain?: number | null
  cumGray?: number | null
}) {
  stockFlowTarget.value = target
  stockFlowOpen.value = true
}

async function onOpenSector(sectorId: string) {
  activeView.value = 'sectors'
  if (!sectorStore.bootstrapped) {
    await sectorStore.bootstrap()
  }
  await sectorStore.selectSector(sectorId)
}

function onOpenSettings() {
  activeView.value = 'settings'
}

function replayMinuteForBoard(): string | null {
  return replayStore.mode === 'live' ? null : replayStore.minute
}

function syncViewStores(tradeDate: string, minute: string) {
  if (activeView.value === 'sectors') {
    sectorStore.setTradeDate(tradeDate, minute)
  }
  if (activeView.value === 'stock') {
    stockStore.setReplayContext(tradeDate, minute)
  }
}

watch(activeView, (view) => {
  if (view === 'home') {
    void boardStore.setReplayContext(replayStore.tradeDate, replayMinuteForBoard())
    return
  }

  // 子页面 store 默认是今日；从首页带历史回放日期切过来时需先对齐顶栏日期。
  syncViewStores(replayStore.tradeDate, replayStore.minute)

  if (view === 'sectors') {
    if (!sectorStore.bootstrapped) {
      void sectorStore.bootstrap()
    } else {
      void sectorStore.loadGroups()
      void sectorStore.loadImportedSectors()
    }
  }
  if (view === 'stock') {
    void stockStore.loadGroups()
    if (stockStore.bootstrapped) {
      void stockStore.reloadForDate()
    }
  }
  if (view === 'hot-list') {
    void hotListStore.bootstrap()
  }
  if (view === 'limit-up-ladder') {
    limitUpLadderStore.setTradeDate(replayStore.tradeDate)
    void limitUpLadderStore.bootstrap()
  }
})

async function refreshAll() {
  refreshing.value = true
  try {
    await marketStore.ensureOverview(replayStore.tradeDate)
    if (activeView.value === 'home') {
      await boardStore.manualRefresh()
    } else if (activeView.value === 'stock') {
      await stockStore.reloadForDate()
    } else if (activeView.value === 'hot-list') {
      await hotListStore.refresh({ force: true })
    } else if (activeView.value === 'limit-up-ladder') {
      limitUpLadderStore.setTradeDate(replayStore.tradeDate)
      await limitUpLadderStore.load({ force: true })
    } else if (activeView.value === 'sectors') {
      if (!sectorStore.bootstrapped) {
        await sectorStore.bootstrap()
      } else {
        await sectorStore.reloadForDate()
      }
      replayStore.minute = sectorStore.replayMinute
    }
  } finally {
    refreshing.value = false
  }
}

watch(
  () => replayStore.tradeDate,
  async (tradeDate, previousDate) => {
    if (!bootstrapped.value) return
    if (previousDate != null && previousDate === tradeDate) return

    marketStore.tradeDate = tradeDate
    await marketStore.ensureOverview(tradeDate)

    const boardMinute = replayStore.mode === 'live' ? null : replayStore.minute
    if (activeView.value === 'home') {
      boardDateLoadInFlight = true
      try {
        await boardStore.setReplayContext(tradeDate, boardMinute)
      } finally {
        boardDateLoadInFlight = false
      }
    } else {
      boardStore.syncReplayDates(tradeDate, boardMinute)
    }

    syncViewStores(tradeDate, replayStore.minute)
    if (activeView.value === 'limit-up-ladder') {
      limitUpLadderStore.setTradeDate(tradeDate)
    }
  },
)

watch(
  () => replayStore.minute,
  (minute, previousMinute) => {
    if (!bootstrapped.value) return
    if (previousMinute != null && previousMinute === minute) return
    if (boardDateLoadInFlight) return

    const tradeDate = replayStore.tradeDate
    const boardMinute = replayStore.mode === 'live' ? null : minute
    if (activeView.value === 'home') {
      boardStore.syncReplayDates(tradeDate, boardMinute)
      const rankingMinute =
        replayStore.mode === 'live' ? replayStore.minute : boardMinute
      if (rankingMinute) {
        void boardStore.syncReplayMinute(rankingMinute)
      }
    } else {
      boardStore.syncReplayDates(tradeDate, boardMinute)
    }
  },
)

onMounted(async () => {
  await replayStore.loadAvailableDates()
  if (!replayStore.tradeDate) {
    const latest = replayStore.availableDates[replayStore.availableDates.length - 1]
    replayStore.tradeDate = latest ?? todayTradeDate()
  }
  marketStore.tradeDate = replayStore.tradeDate
  bootstrapped.value = true
  await marketStore.ensureOverview(replayStore.tradeDate)
  void boardStore.setReplayContext(replayStore.tradeDate, replayMinuteForBoard())
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

      <SectorWorkspace
        v-else-if="activeView === 'sectors'"
        @open-settings="onOpenSettings"
      />

      <StockWorkspace
        v-else-if="activeView === 'stock'"
        :initial-symbol="selectedStock"
        @open-settings="onOpenSettings"
      />

      <HotListWorkspace
        v-else-if="activeView === 'hot-list'"
        @open-stock="onOpenStock"
        @open-sector="onOpenSector"
      />

      <LimitUpLadderWorkspace
        v-else-if="activeView === 'limit-up-ladder'"
        @open-stock="onOpenStock"
      />

      <CycleReplayWorkspace v-else-if="activeView === 'cycle-replay'" />

      <HealthPage v-else-if="activeView === 'health'" />
      <SettingsPage v-else-if="activeView === 'settings'" />
    </main>

    <p v-if="shellError" class="workbench-error">
      {{ shellError }}
    </p>

    <MemberStockFlowModal
      v-model:show="stockFlowOpen"
      :symbol="stockFlowTarget?.symbol ?? ''"
      :name="stockFlowTarget?.name ?? ''"
      :trade-date="replayStore.tradeDate"
      :replay-minute="replayStore.minute"
      :change-pct="stockFlowTarget?.changePct"
      :cum-main="stockFlowTarget?.cumMain"
      :cum-gray="stockFlowTarget?.cumGray"
    />
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
