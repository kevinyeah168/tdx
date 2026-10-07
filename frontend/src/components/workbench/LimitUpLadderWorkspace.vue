<script setup lang="ts">
import {
  CloseCircleOutline,
  FlameOutline,
  LayersOutline,
  PieChartOutline,
  SparklesOutline,
  TrophyOutline,
} from '@vicons/ionicons5'
import { NEmpty, NIcon, NSpin, NTag } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'

import type { LimitUpLadderTier } from '@/api/limitUpLadder'
import { HOT_LIST_OFF_HOURS_POLL_MS, HOT_LIST_POLL_MS } from '@/constants/refresh'
import { useLimitUpLadderStore } from '@/stores/limitUpLadderStore'
import { useReplayStore } from '@/stores/replayStore'
import { chgTone, fmtMoneyCompact, fmtPct, toneClass } from '@/utils/format'
import { isLiveTradingClock } from '@/utils/tradingSession'
import { todayTradeDate } from '@/utils/tradeDate'

const emit = defineEmits<{
  openStock: [target: { symbol: string; name: string; changePct?: number | null }]
}>()

const limitUpStore = useLimitUpLadderStore()
const replayStore = useReplayStore()
const { data, loading, error, tradeDate, isSnapshot } = storeToRefs(limitUpStore)

let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollInFlight = false

const tiers = computed(() => data.value?.tiers ?? [])
const summary = computed(() => data.value?.summary)

const fetchedAtLabel = computed(() => {
  const raw = data.value?.fetched_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false })
})

const dataKindLabel = computed(() => {
  if (!data.value) return ''
  if (isSnapshot.value && tradeDate.value !== todayTradeDate()) return '历史快照'
  if (isSnapshot.value) return '日终快照'
  return '实时'
})

function pollIntervalMs(): number {
  return isLiveTradingClock() ? HOT_LIST_POLL_MS : HOT_LIST_OFF_HOURS_POLL_MS
}

function shouldPoll(): boolean {
  return tradeDate.value === todayTradeDate()
}

function clearPollTimer() {
  if (pollTimer !== undefined) {
    clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

function scheduleNextPoll() {
  clearPollTimer()
  if (!shouldPoll()) return
  pollTimer = setTimeout(() => {
    void (async () => {
      await tickPoll()
      scheduleNextPoll()
    })()
  }, pollIntervalMs())
}

async function tickPoll() {
  if (!shouldPoll() || pollInFlight || document.visibilityState === 'hidden') return
  pollInFlight = true
  try {
    await limitUpStore.refresh()
  } finally {
    pollInFlight = false
  }
}

function onVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    clearPollTimer()
    return
  }
  void tickPoll()
  scheduleNextPoll()
}

function tierAccentClass(tier: LimitUpLadderTier): string {
  if (tier.board_days >= 7) return 'ladder-tier--max'
  if (tier.board_days >= 4) return 'ladder-tier--high'
  if (tier.board_days >= 2) return 'ladder-tier--mid'
  return 'ladder-tier--first'
}

function tierBadgeText(tier: LimitUpLadderTier): string {
  if (tier.board_days >= 7) return '7+'
  return String(tier.board_days)
}

function fmtSealAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return fmtMoneyCompact(value)
}

watch(
  () => replayStore.tradeDate,
  (nextDate) => {
    limitUpStore.setTradeDate(nextDate)
    clearPollTimer()
    scheduleNextPoll()
  },
)

onMounted(() => {
  limitUpStore.setTradeDate(replayStore.tradeDate)
  void limitUpStore.bootstrap()
  scheduleNextPoll()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  clearPollTimer()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="limit-up-workspace">
    <NSpin class="limit-up-spin" :show="loading">
      <section class="panel-card limit-up-panel">
        <header class="limit-up-top">
          <div class="limit-up-title-row">
            <h2 class="panel-title">涨停梯队</h2>
            <NTag size="small" :bordered="false" class="tag-em">东财</NTag>
            <NTag size="small" :bordered="false">{{ tradeDate }}</NTag>
            <NTag v-if="dataKindLabel" size="small" type="info" :bordered="false">{{ dataKindLabel }}</NTag>
            <span v-if="fetchedAtLabel" class="limit-up-updated">更新 {{ fetchedAtLabel }}</span>
          </div>

          <div v-if="summary" class="emotion-strip">
            <div class="emotion-chip emotion-chip--primary">
              <NIcon class="emotion-icon" :component="FlameOutline" />
              <span class="emotion-label">涨停</span>
              <span class="emotion-value">{{ summary.limit_up_count }}</span>
            </div>
            <div class="emotion-chip emotion-chip--hot">
              <NIcon class="emotion-icon" :component="TrophyOutline" />
              <span class="emotion-label">最高板</span>
              <span class="emotion-value">{{ summary.max_board || '—' }}</span>
            </div>
            <div class="emotion-chip">
              <NIcon class="emotion-icon" :component="LayersOutline" />
              <span class="emotion-label">连板</span>
              <span class="emotion-value">{{ summary.multi_board_count }}</span>
            </div>
            <div class="emotion-chip">
              <NIcon class="emotion-icon" :component="SparklesOutline" />
              <span class="emotion-label">首板</span>
              <span class="emotion-value">{{ summary.first_board_count }}</span>
            </div>
            <div class="emotion-chip emotion-chip--warn">
              <NIcon class="emotion-icon" :component="CloseCircleOutline" />
              <span class="emotion-label">炸板</span>
              <span class="emotion-value">{{ summary.broken_count }}</span>
            </div>
            <div class="emotion-chip emotion-chip--warn">
              <NIcon class="emotion-icon" :component="PieChartOutline" />
              <span class="emotion-label">炸板率</span>
              <span class="emotion-value">
                {{ summary.break_rate_pct == null ? '—' : `${summary.break_rate_pct}%` }}
              </span>
            </div>
          </div>
        </header>

        <div v-if="tiers.length" class="limit-up-body">
          <section
            v-for="tier in tiers"
            :key="tier.board_days"
            class="ladder-tier"
            :class="tierAccentClass(tier)"
          >
            <header class="ladder-tier-head">
              <span class="ladder-tier-badge">
                <span class="ladder-tier-num">{{ tierBadgeText(tier) }}</span>
                <span class="ladder-tier-unit">板</span>
              </span>
              <span class="ladder-tier-title">{{ tier.label }}</span>
              <span class="ladder-tier-count">{{ tier.count }} 只</span>
            </header>

            <div class="ladder-tier-grid">
              <button
                v-for="item in tier.items"
                :key="item.symbol"
                type="button"
                class="stock-card"
                @click="emit('openStock', { symbol: item.symbol, name: item.name, changePct: item.change_pct })"
              >
                <div class="stock-card-head">
                  <span class="stock-card-name">{{ item.name }}</span>
                  <span class="stock-card-code">{{ item.code }}</span>
                </div>
                <div class="stock-card-meta">
                  <span class="stock-card-pct" :class="toneClass(chgTone(item.change_pct))">
                    {{ fmtPct(item.change_pct) }}
                  </span>
                  <span v-if="item.first_seal_time" class="stock-card-time">{{ item.first_seal_time }}</span>
                </div>
                <div class="stock-card-foot">
                  <span v-if="item.industry" class="stock-card-industry">{{ item.industry }}</span>
                  <span v-if="item.seal_amount != null" class="stock-card-seal">
                    封 {{ fmtSealAmount(item.seal_amount) }}
                  </span>
                  <span v-if="item.limit_stats" class="stock-card-stats">{{ item.limit_stats }}</span>
                </div>
              </button>
            </div>
          </section>
        </div>

        <NEmpty v-else class="limit-up-empty" description="暂无涨停梯队数据" />
      </section>
    </NSpin>

    <p v-if="error" class="limit-up-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.limit-up-workspace {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 6px;
}

.limit-up-spin {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.limit-up-spin :deep(.n-spin-container),
.limit-up-spin :deep(.n-spin-content) {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.limit-up-panel {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  padding: 6px 8px;
  gap: 6px;
}

.limit-up-top {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: 6px;
}

.limit-up-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.panel-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
}

.tag-em {
  background: color-mix(in srgb, #f97316 14%, var(--panel)) !important;
  color: #ea580c !important;
}

.limit-up-updated {
  margin-left: auto;
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
}

.emotion-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.emotion-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--border) 75%, transparent);
  background: color-mix(in srgb, var(--panel) 94%, var(--border));
}

.emotion-chip--primary {
  border-color: color-mix(in srgb, #e11d48 30%, var(--border));
  background: color-mix(in srgb, #e11d48 8%, var(--panel));
}

.emotion-chip--primary .emotion-icon {
  color: #e11d48;
}

.emotion-chip--hot .emotion-value {
  color: #e11d48;
}

.emotion-chip--hot .emotion-icon {
  color: #e11d48;
}

.emotion-chip--warn {
  border-color: color-mix(in srgb, #f97316 28%, var(--border));
  background: color-mix(in srgb, #f97316 7%, var(--panel));
}

.emotion-chip--warn .emotion-icon,
.emotion-chip--warn .emotion-value {
  color: #ea580c;
}

.emotion-icon {
  font-size: 14px;
  flex-shrink: 0;
  color: var(--muted);
}

.emotion-label {
  font-size: 11px;
  color: var(--muted);
}

.emotion-value {
  font-size: 13px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.limit-up-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  padding-right: 2px;
}

.ladder-tier {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
  background: var(--panel);
}

.ladder-tier--max {
  border-color: color-mix(in srgb, #e11d48 32%, var(--border));
}

.ladder-tier--high {
  border-color: color-mix(in srgb, #f97316 28%, var(--border));
}

.ladder-tier-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
  background: color-mix(in srgb, var(--border) 18%, var(--panel));
}

.ladder-tier--max .ladder-tier-head {
  background: color-mix(in srgb, #e11d48 10%, var(--panel));
}

.ladder-tier--high .ladder-tier-head {
  background: color-mix(in srgb, #f97316 8%, var(--panel));
}

.ladder-tier--mid .ladder-tier-head {
  background: color-mix(in srgb, #f59e0b 7%, var(--panel));
}

.ladder-tier-badge {
  display: inline-flex;
  align-items: baseline;
  gap: 1px;
  min-width: 42px;
  justify-content: center;
  padding: 2px 8px;
  border-radius: 6px;
  color: #fff;
  font-weight: 800;
  line-height: 1.2;
}

.ladder-tier--max .ladder-tier-badge {
  background: linear-gradient(135deg, #e11d48, #be123c);
}

.ladder-tier--high .ladder-tier-badge {
  background: linear-gradient(135deg, #f97316, #ea580c);
}

.ladder-tier--mid .ladder-tier-badge {
  background: linear-gradient(135deg, #f59e0b, #d97706);
}

.ladder-tier--first .ladder-tier-badge {
  background: linear-gradient(135deg, #64748b, #475569);
}

.ladder-tier-num {
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.ladder-tier-unit {
  font-size: 10px;
  font-weight: 600;
}

.ladder-tier-title {
  font-size: 12px;
  font-weight: 700;
}

.ladder-tier-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.ladder-tier-grid {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: repeat(auto-fill, minmax(152px, 1fr));
  grid-auto-rows: min-content;
  align-items: start;
  gap: 5px;
  padding: 6px;
}

.stock-card {
  display: flex;
  height: auto;
  align-self: start;
  flex-direction: column;
  gap: 2px;
  padding: 5px 7px;
  border: 1px solid color-mix(in srgb, var(--border) 65%, transparent);
  border-radius: 7px;
  background: var(--panel);
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}

.stock-card:hover {
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: color-mix(in srgb, var(--accent) 5%, var(--panel));
}

.ladder-tier--max .stock-card {
  border-color: color-mix(in srgb, #e11d48 16%, var(--border));
}

.stock-card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px;
}

.stock-card-name {
  font-size: 12px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stock-card-code {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.stock-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}

.stock-card-pct {
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.stock-card-time {
  font-size: 10px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.stock-card-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 6px;
  font-size: 9px;
  color: var(--muted);
  line-height: 1.25;
}

.stock-card-industry {
  padding: 1px 5px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--border) 50%, transparent);
  color: var(--text);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stock-card-seal {
  font-variant-numeric: tabular-nums;
}

.stock-card-stats {
  font-variant-numeric: tabular-nums;
}

.limit-up-empty {
  padding: 2rem 0;
}

.limit-up-error {
  flex-shrink: 0;
  margin: 0;
  padding: 0 4px;
  font-size: 12px;
  color: #ef4444;
}

@media (max-width: 720px) {
  .ladder-tier-grid {
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  }
}
</style>
