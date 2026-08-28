<script setup lang="ts">
import { NTag } from 'naive-ui'
import { onBeforeUnmount, onMounted, watch } from 'vue'

import { syncWorkbenchPriorityTargets } from '@/api/workbenchBoard'
import MarketPanel from '@/components/pages/MarketPanel.vue'
import SectorPickerDrawer from '@/components/sector/SectorPickerDrawer.vue'
import StockPickerDrawer from '@/components/stock/StockPickerDrawer.vue'
import { WORKBENCH_REFRESH_MS } from '@/constants/refresh'
import { useBoardStore } from '@/stores/boardStore'
import { useReplayStore } from '@/stores/replayStore'

const boardStore = useBoardStore()
const replayStore = useReplayStore()

let pollTimer: ReturnType<typeof setInterval> | undefined
let tickTimer: ReturnType<typeof setInterval> | undefined
let syncTimer: ReturnType<typeof setInterval> | undefined

async function syncFromReplay() {
  const minute = replayStore.mode === 'live' ? null : replayStore.minute
  await boardStore.setReplayContext(replayStore.tradeDate, minute)
}

onMounted(async () => {
  await syncFromReplay()
  void syncWorkbenchPriorityTargets()

  pollTimer = setInterval(async () => {
    if (boardStore.isPanelBusy) return
    if (replayStore.mode === 'live') {
      boardStore.replayMinute = null
    }
    await boardStore.loadBoard()
    boardStore.resetCountdown()
  }, WORKBENCH_REFRESH_MS)

  syncTimer = setInterval(() => {
    void syncWorkbenchPriorityTargets({
      linkageSectorId: boardStore.linkageSectorId,
      linkageSectorName: boardStore.linkageSectorName,
    })
  }, WORKBENCH_REFRESH_MS * 12)

  tickTimer = setInterval(() => {
    boardStore.tickCountdown()
  }, 1000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (tickTimer) clearInterval(tickTimer)
  if (syncTimer) clearInterval(syncTimer)
})

watch(
  () => [replayStore.tradeDate, replayStore.minute] as const,
  () => {
    void syncFromReplay()
  },
)
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
