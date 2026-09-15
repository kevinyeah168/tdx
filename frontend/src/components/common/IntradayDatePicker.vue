<script setup lang="ts">
import { CalendarOutline } from '@vicons/ionicons5'
import {
  NButton,
  NIcon,
  NPopover,
  NScrollbar,
  NSpace,
  NTag,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, ref } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import { isWeekdayDate } from '@/utils/tradingSession'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const { board, stockViewDate, sectorViewDate } = storeToRefs(boardStore)

const showPopover = ref(false)

const tradeDate = computed(() => board.value.trading_session?.tradeDate)

const viewDate = computed(() =>
  props.mode === 'stock' ? stockViewDate.value : sectorViewDate.value,
)

/** Persisted intraday samples plus today (always selectable on trading days). */
const savedDates = computed(() => {
  const raw =
    props.mode === 'stock'
      ? board.value.stock_intraday_dates || []
      : board.value.sector_intraday_dates || []
  return [...new Set(raw.filter((d) => isWeekdayDate(d)))]
})

const selectableDates = computed(() => {
  const dates = new Set(savedDates.value)
  const today = tradeDate.value
  const session = board.value.trading_session
  if (today && session?.isTradingDay && isWeekdayDate(today)) dates.add(today)
  return [...dates].sort((a, b) => b.localeCompare(a))
})

function dateHasSamples(date: string) {
  return savedDates.value.includes(date)
}

const statusLabel = computed(() => {
  const session = board.value.trading_session
  const viewing = viewDate.value
  const today = tradeDate.value

  if (viewing && today && viewing !== today) {
    if (session?.marketStatus === 'pre_open') return '盘前 · 历史回看'
    return dateHasSamples(viewing) ? '历史回看' : '无采样数据'
  }

  if (!viewing || !today || viewing !== today) return '—'

  if (session?.marketStatus === 'pre_open') return '尚未开盘'
  if (session?.marketStatus === 'non_trading_day') return '非交易日'
  if (session?.sessionStatus === 'open') {
    return dateHasSamples(today) ? '实时采样' : '开盘采集中'
  }
  if (session?.marketStatus === 'lunch_break') {
    return dateHasSamples(today) ? '午间休市' : '午间 · 待采样'
  }
  if (session?.marketStatus === 'closed' && session?.isTradingDay) {
    return dateHasSamples(today) ? '今日收盘' : '今日未采样'
  }
  return dateHasSamples(today) ? '已采样' : '待采样'
})

const statusType = computed(() => {
  const label = statusLabel.value
  if (label.includes('历史') || label.includes('盘前')) return 'warning'
  if (label === '实时采样' || label === '今日收盘' || label === '开盘采集中') return 'success'
  if (label === '尚未开盘' || label === '待采样' || label === '今日未采样') return 'default'
  return 'default'
})

function pickDate(date: string) {
  if (props.mode === 'stock') boardStore.setStockViewDate(date)
  else boardStore.setSectorViewDate(date)
  showPopover.value = false
}

const displayLabel = computed(() => {
  const d = viewDate.value
  if (!d) return '选择交易日'
  if (d === tradeDate.value) return `${d}（今日）`
  return d
})

function rowHint(date: string) {
  if (date === tradeDate.value) {
    return dateHasSamples(date) ? '今日 · 有数据' : '今日 · 待开盘'
  }
  return dateHasSamples(date) ? '已保存' : ''
}
</script>

<template>
  <NSpace align="center" :size="8" class="shrink-0">
    <NPopover
      v-model:show="showPopover"
      trigger="click"
      placement="bottom-end"
      :width="240"
      class="trade-date-popover"
    >
      <template #trigger>
        <NButton
          size="small"
          quaternary
          class="trade-date-trigger"
          :disabled="!selectableDates.length"
        >
          <template #icon>
            <NIcon :component="CalendarOutline" />
          </template>
          <span class="trade-date-text">{{ displayLabel }}</span>
        </NButton>
      </template>

      <div class="trade-date-panel">
        <div class="panel-head">
          <span class="panel-title">交易日</span>
          <span class="panel-hint">今日可选 · 历史仅已保存</span>
        </div>
        <NScrollbar v-if="selectableDates.length" style="max-height: 280px">
          <div class="date-list">
            <button
              v-for="d in selectableDates"
              :key="d"
              type="button"
              class="date-item"
              :class="{ active: viewDate === d }"
              @click="pickDate(d)"
            >
              <span class="date-main">{{ d }}</span>
              <NTag
                v-if="d === tradeDate"
                size="tiny"
                round
                :bordered="false"
                :type="dateHasSamples(d) ? 'info' : 'default'"
              >
                {{ dateHasSamples(d) ? '今日' : '待采样' }}
              </NTag>
              <span v-else-if="rowHint(d)" class="date-sub">{{ rowHint(d) }}</span>
            </button>
          </div>
        </NScrollbar>
        <p v-else class="empty-hint">暂无可选交易日</p>
      </div>
    </NPopover>

    <NTag size="small" :type="statusType">
      {{ statusLabel }}
    </NTag>
  </NSpace>
</template>

<style scoped>
.trade-date-trigger {
  min-width: 180px;
  max-width: 240px;
  justify-content: flex-start;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--panel) 96%, var(--bg));
}

.trade-date-trigger:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
}

.trade-date-text {
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.trade-date-panel {
  padding: 4px 0;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 12px 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 6px;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.panel-hint {
  font-size: 11px;
  color: var(--muted);
}

.date-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 6px 4px;
}

.date-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.date-item:hover {
  background: color-mix(in srgb, var(--accent) 8%, var(--panel));
}

.date-item.active {
  background: color-mix(in srgb, var(--accent) 14%, var(--panel));
  color: var(--accent);
  font-weight: 600;
}

.date-main {
  flex: 1;
  text-align: left;
}

.date-sub {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.empty-hint {
  margin: 8px 12px;
  font-size: 12px;
  color: var(--muted);
}
</style>
