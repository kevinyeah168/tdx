<script setup lang="ts">
import { NDatePicker, NTag } from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'

import { WORKBENCH_REFRESH_MS } from '@/constants/refresh'
import { useMarketStore } from '@/stores/marketStore'
import { useReplayStore } from '@/stores/replayStore'
import { isWeekdayDate } from '@/utils/tradingSession'
import { syncReplayMinuteForDate } from '@/utils/replayMinute'
import { localDateFromTimestamp, todayTradeDate } from '@/utils/tradeDate'

const replayStore = useReplayStore()
const marketStore = useMarketStore()

const selectableDates = computed(() => {
  const dates = new Set(replayStore.availableDates.filter((d) => isWeekdayDate(d)))
  const today = todayTradeDate()
  if (isWeekdayDate(today)) dates.add(today)
  return [...dates].sort((a, b) => b.localeCompare(a))
})

function isDateDisabled(ts: number): boolean {
  const d = localDateFromTimestamp(ts)
  if (!isWeekdayDate(d)) return true
  return !selectableDates.value.includes(d)
}

function applyLocalMinute(tradeDate?: string, opts?: { resetToLatest?: boolean }) {
  const date = tradeDate || replayStore.tradeDate
  const overview = marketStore.overviewFor(date) ?? marketStore.overview
  replayStore.minute = syncReplayMinuteForDate(date, overview, {
    resetToLatest: opts?.resetToLatest,
    currentMinute: replayStore.minute,
  })
  replayStore.mode = date === todayTradeDate() ? 'live' : 'replay'
}

function onDateChange(date: string | null) {
  if (!date || !isWeekdayDate(date) || !selectableDates.value.includes(date)) return
  replayStore.tradeDate = date
}

let liveMinuteTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  liveMinuteTimer = setInterval(() => {
    if (replayStore.mode !== 'live' || replayStore.tradeDate !== todayTradeDate()) return
    applyLocalMinute(replayStore.tradeDate, { resetToLatest: true })
  }, WORKBENCH_REFRESH_MS)
})

onBeforeUnmount(() => {
  if (liveMinuteTimer) clearInterval(liveMinuteTimer)
})

watch(
  () => replayStore.tradeDate,
  (date) => {
    applyLocalMinute(date, { resetToLatest: true })
  },
  { immediate: true },
)

defineExpose({ applyLocalMinute })
</script>

<template>
  <div class="replay-controls">
    <NTag :type="replayStore.mode === 'live' ? 'success' : 'warning'" size="small" :bordered="false">
      {{ replayStore.mode === 'live' ? '实时' : '回放' }}
    </NTag>
    <NDatePicker
      :formatted-value="replayStore.tradeDate"
      value-format="yyyy-MM-dd"
      type="date"
      size="small"
      :actions="null"
      class="replay-date"
      :is-date-disabled="isDateDisabled"
      @update:formatted-value="onDateChange"
    />
  </div>
</template>

<style scoped>
.replay-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.replay-date {
  width: 124px;
}
</style>
