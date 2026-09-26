<script setup lang="ts">
import { NDatePicker, NTag } from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'

import { fetchReplayMinutes } from '@/api/replay'
import { WORKBENCH_REFRESH_MS } from '@/constants/refresh'
import { useReplayStore } from '@/stores/replayStore'
import { isWeekdayDate, shouldFetchMarketDataForDate } from '@/utils/tradingSession'
import { filterLiveReplayMinutes, capLiveReplayMinute } from '@/utils/tradingTimeline'
import { localDateFromTimestamp, todayTradeDate } from '@/utils/tradeDate'

const replayStore = useReplayStore()

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

async function loadMinutes(tradeDate?: string, opts?: { resetToLatest?: boolean }) {
  const date = tradeDate || replayStore.tradeDate
  if (!shouldFetchMarketDataForDate(date)) {
    replayStore.minute = '09:31'
    replayStore.mode = date === todayTradeDate() ? 'live' : 'replay'
    return
  }
  try {
    const payload = await fetchReplayMinutes(date)
    const minutes = filterLiveReplayMinutes(payload.minutes, date)
    const latest =
      capLiveReplayMinute(
        payload.latest_available_minute ??
          payload.latest_sector_minute ??
          payload.latest_complete_minute ??
          minutes[minutes.length - 1] ??
          '09:31',
        date,
      ) ??
      minutes[minutes.length - 1] ??
      '09:31'
    const isToday = date === todayTradeDate()
    replayStore.mode = isToday ? 'live' : 'replay'
    const shouldUseLatest =
      opts?.resetToLatest === true ||
      replayStore.mode === 'live' ||
      !minutes.includes(replayStore.minute)
    if (shouldUseLatest) {
      replayStore.minute = latest
    }
  } catch {
    replayStore.minute = '09:31'
    replayStore.mode = date === todayTradeDate() ? 'live' : 'replay'
  }
}

function onDateChange(date: string | null) {
  if (!date || !isWeekdayDate(date) || !selectableDates.value.includes(date)) return
  replayStore.tradeDate = date
}

let liveMinuteTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  liveMinuteTimer = setInterval(() => {
    if (replayStore.mode !== 'live' || replayStore.tradeDate !== todayTradeDate()) return
    if (!shouldFetchMarketDataForDate(replayStore.tradeDate)) return
    void loadMinutes(replayStore.tradeDate)
  }, WORKBENCH_REFRESH_MS)
})

onBeforeUnmount(() => {
  if (liveMinuteTimer) clearInterval(liveMinuteTimer)
})

watch(
  () => replayStore.tradeDate,
  (date) => {
    void loadMinutes(date, { resetToLatest: true })
  },
  { immediate: true },
)

defineExpose({ loadMinutes })
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
