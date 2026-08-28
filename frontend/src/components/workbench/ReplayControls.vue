<script setup lang="ts">
import { NButton, NDatePicker, NSelect, NTag } from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchReplayMinutes } from '@/api/replay'
import { WORKBENCH_REFRESH_MS } from '@/constants/refresh'
import { useReplayStore } from '@/stores/replayStore'
import { currentTradingClockMinute, filterLiveReplayMinutes, capLiveReplayMinute } from '@/utils/tradingTimeline'
import { todayTradeDate } from '@/utils/tradeDate'

const replayStore = useReplayStore()
const minuteOptions = ref<{ label: string; value: string }[]>([])
const loadingMinutes = ref(false)

const selectableDates = computed(() => {
  const dates = new Set(replayStore.availableDates)
  dates.add(todayTradeDate())
  return [...dates].sort((a, b) => b.localeCompare(a))
})

async function loadMinutes(tradeDate?: string, opts?: { pinMinute?: boolean }) {
  const date = tradeDate || replayStore.tradeDate
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
    if (opts?.pinMinute || replayStore.mode === 'replay') {
      if (!minuteOptions.value.some((item) => item.value === replayStore.minute)) {
        replayStore.minute = latest
      }
    } else {
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
  if (!date) return
  replayStore.tradeDate = date
  await loadMinutes(date)
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
    void loadMinutes(replayStore.tradeDate)
  }, WORKBENCH_REFRESH_MS)
})

onBeforeUnmount(() => {
  if (liveMinuteTimer) clearInterval(liveMinuteTimer)
})

watch(
  () => replayStore.tradeDate,
  (date) => {
    void loadMinutes(date)
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
      :is-date-disabled="(ts: number) => {
        const d = new Date(ts).toISOString().slice(0, 10)
        return !selectableDates.includes(d)
      }"
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
