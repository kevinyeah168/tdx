<script setup lang="ts">
import { NButton, NDatePicker, NSelect, NTag } from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchReplayMinutes } from '@/api/replay'
import { WORKBENCH_REFRESH_MS } from '@/constants/refresh'
import { useReplayStore } from '@/stores/replayStore'
import { isWeekdayDate, shouldFetchMarketDataForDate } from '@/utils/tradingSession'
import { filterLiveReplayMinutes, capLiveReplayMinute } from '@/utils/tradingTimeline'
import { localDateFromTimestamp, todayTradeDate } from '@/utils/tradeDate'

const replayStore = useReplayStore()
const minuteOptions = ref<{ label: string; value: string }[]>([])
const loadingMinutes = ref(false)

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
    minuteOptions.value = []
    replayStore.minute = '09:31'
    replayStore.mode = date === todayTradeDate() ? 'live' : 'replay'
    return
  }
  loadingMinutes.value = true
  try {
    const payload = await fetchReplayMinutes(date)
    const minutes = filterLiveReplayMinutes(payload.minutes, date)
    minuteOptions.value = minutes.map((minute) => ({ label: minute, value: minute }))
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
      !minuteOptions.value.some((item) => item.value === replayStore.minute)
    if (shouldUseLatest) {
      replayStore.minute = latest
    }
  } catch {
    minuteOptions.value = []
    replayStore.minute = '09:31'
    replayStore.mode = date === todayTradeDate() ? 'live' : 'replay'
  } finally {
    loadingMinutes.value = false
  }
}

async function onDateChange(date: string | null) {
  if (!date || !isWeekdayDate(date) || !selectableDates.value.includes(date)) return
  replayStore.tradeDate = date
  await loadMinutes(date, { resetToLatest: true })
}

async function setLive() {
  replayStore.setLive()
  await loadMinutes(todayTradeDate())
}

function onMinutePick(minute: string) {
  replayStore.setReplay(replayStore.tradeDate, minute)
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
    <NSelect
      v-model:value="replayStore.minute"
      :options="minuteOptions"
      :disabled="!minuteOptions.length"
      :loading="loadingMinutes"
      size="small"
      class="replay-minute"
      @update:value="onMinutePick"
    />
    <NButton size="small" quaternary @click="setLive">回到实时</NButton>
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

.replay-minute {
  width: 84px;
}
</style>
