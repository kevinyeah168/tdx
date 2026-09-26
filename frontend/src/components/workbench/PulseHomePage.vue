<script setup lang="ts">
import { NTag } from 'naive-ui'
import { onBeforeUnmount, onMounted } from 'vue'

import MarketPanel from '@/components/pages/MarketPanel.vue'
import SectorPickerDrawer from '@/components/sector/SectorPickerDrawer.vue'
import StockPickerDrawer from '@/components/stock/StockPickerDrawer.vue'
import { CATALOG_REFRESH_MS, WORKBENCH_REFRESH_MS } from '@/constants/refresh'
import { useBoardStore } from '@/stores/boardStore'
import { useReplayStore } from '@/stores/replayStore'
import { shouldFetchMarketDataForDate, shouldPollLiveWorkbench } from '@/utils/tradingSession'
import { todayTradeDate } from '@/utils/tradeDate'

const boardStore = useBoardStore()
const replayStore = useReplayStore()

let pollTimer: ReturnType<typeof setInterval> | undefined
let catalogTimer: ReturnType<typeof setInterval> | undefined
let tickTimer: ReturnType<typeof setInterval> | undefined
let pollInFlight = false
let catalogPollInFlight = false

onMounted(() => {
  pollTimer = setInterval(async () => {
    if (pollInFlight || boardStore.isPanelBusy) return

    const isLive = replayStore.mode === 'live'
    const tradeDate = replayStore.tradeDate || todayTradeDate()
    const historicalSectorView = boardStore.isHistoricalSectorView()
    const pollQuotes =
      isLive &&
      !historicalSectorView &&
      shouldFetchMarketDataForDate(tradeDate) &&
      shouldPollLiveWorkbench({ mode: replayStore.mode, tradeDate })

    if (!pollQuotes && !isLive) return
    if (isLive && !pollQuotes) return

    pollInFlight = true
    try {
      if (isLive) boardStore.replayMinute = null
      await boardStore.loadBoard()
      boardStore.resetCountdown()
    } finally {
      pollInFlight = false
    }
  }, WORKBENCH_REFRESH_MS)

  catalogTimer = setInterval(() => {
    if (catalogPollInFlight || pollInFlight || boardStore.isPanelBusy) return
    if (replayStore.mode !== 'live') return
    if (boardStore.stockSourceMode !== 'linkage' || !boardStore.linkageSectorId) return

    const sectorViewDate =
      boardStore.sectorViewDate ?? boardStore.board.sector_view_date ?? todayTradeDate()
    if (!shouldFetchMarketDataForDate(sectorViewDate)) return

    const tradeDate = replayStore.tradeDate || todayTradeDate()
    if (
      shouldPollLiveWorkbench({ mode: replayStore.mode, tradeDate }) &&
      !boardStore.isHistoricalSectorView()
    ) {
      return
    }

    catalogPollInFlight = true
    void boardStore.refreshHomeCatalogIfChanged().finally(() => {
      catalogPollInFlight = false
    })
  }, CATALOG_REFRESH_MS)

  tickTimer = setInterval(() => {
    boardStore.tickCountdown()
  }, 1000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (catalogTimer) clearInterval(catalogTimer)
  if (tickTimer) clearInterval(tickTimer)
})
</script>

<template>
  <div class="pulse-home">
    <div v-if="boardStore.board.error" class="pulse-error">
      <NTag type="error" size="small">{{ boardStore.board.error }}</NTag>
    </div>

    <div class="pulse-grid">
      <div class="panel-card pulse-panel">
        <MarketPanel mode="sector" />
      </div>
      <div class="panel-card pulse-panel">
        <MarketPanel mode="stock" />
      </div>
    </div>

    <SectorPickerDrawer />
    <StockPickerDrawer />
  </div>
</template>

<style scoped>
.pulse-home {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: 6px;
}

.pulse-error {
  flex-shrink: 0;
}

.pulse-grid {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.pulse-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: 8px;
  overflow: hidden;
}

@media (max-width: 1200px) {
  .pulse-grid {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .pulse-panel {
    min-height: 520px;
  }
}
</style>
