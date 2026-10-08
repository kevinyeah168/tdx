<script setup lang="ts">
import { AlarmOutline, CashOutline, PulseOutline, StatsChartOutline } from '@vicons/ionicons5'
import { NDataTable, NEmpty, NIcon, NRadioButton, NRadioGroup, NSpin, NTag, type DataTableColumns } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h, onBeforeUnmount, onMounted, watch } from 'vue'

import type { AuctionBoardItem, AuctionBoardSort } from '@/api/auctionBoard'
import { AUCTION_POLL_MS } from '@/constants/refresh'
import { useAuctionBoardStore } from '@/stores/auctionBoardStore'
import { useReplayStore } from '@/stores/replayStore'
import { chgTone, fmtMoneyCompact, fmtPct, toneClass } from '@/utils/format'
import { todayTradeDate } from '@/utils/tradeDate'

const emit = defineEmits<{
  openStock: [target: { symbol: string; name: string; changePct?: number | null }]
}>()

const auctionStore = useAuctionBoardStore()
const replayStore = useReplayStore()
const { data, loading, error, tradeDate, sort, shouldPoll } = storeToRefs(auctionStore)

let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollInFlight = false

const items = computed(() => data.value?.items ?? [])

const fetchedAtLabel = computed(() => {
  const raw = data.value?.fetched_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false })
})

const phaseLabel = computed(() => {
  switch (data.value?.phase) {
    case 'waiting':
      return '竞价未开始'
    case 'auction':
      return '竞价中'
    case 'post_auction':
      return '已定盘'
    case 'closed':
      return data.value?.data_kind === 'snapshot' ? '历史快照' : '竞价已结束'
    default:
      return ''
  }
})

const phaseTagType = computed(() => {
  switch (data.value?.phase) {
    case 'auction':
      return 'error'
    case 'post_auction':
      return 'warning'
    case 'waiting':
      return 'default'
    default:
      return 'info'
  }
})

const dataKindLabel = computed(() => {
  if (!data.value) return ''
  if (auctionStore.isSnapshot && tradeDate.value !== todayTradeDate()) return '历史快照'
  if (auctionStore.isSnapshot) return '日终快照'
  return '实时'
})

const sourceLabel = computed(() => {
  const src = data.value?.source ?? ''
  if (src.includes('darktrade')) return '竞价资金榜'
  if (src.includes('clist')) return '量能榜单'
  return ''
})

const emptyDescription = computed(() => {
  if (data.value?.phase === 'waiting') return '竞价尚未开始（09:15）'
  if (data.value?.phase === 'closed' && data.value?.data_kind !== 'snapshot') {
    return '竞价已结束，暂无当日快照（下一交易日 09:25 后自动留存）'
  }
  return '暂无盘前竞价数据'
})

function clearPollTimer() {
  if (pollTimer !== undefined) {
    clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

function scheduleNextPoll() {
  clearPollTimer()
  if (!shouldPoll.value) return
  pollTimer = setTimeout(() => {
    void (async () => {
      await tickPoll()
      scheduleNextPoll()
    })()
  }, AUCTION_POLL_MS)
}

async function tickPoll() {
  if (!shouldPoll.value || pollInFlight || document.visibilityState === 'hidden') return
  pollInFlight = true
  try {
    await auctionStore.refresh()
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

function onSortChange(value: AuctionBoardSort) {
  auctionStore.setSort(value)
}

function fmtVolume(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万手`
  return `${value.toFixed(0)}手`
}

function renderPct(value: number | null | undefined) {
  const tone = chgTone(value)
  return h('span', { class: ['auction-pct', toneClass(tone)] }, fmtPct(value))
}

const columns = computed<DataTableColumns<AuctionBoardItem>>(() => [
  { title: '排名', key: 'rank', width: 52, align: 'center' },
  {
    title: '名称',
    key: 'name',
    minWidth: 88,
    ellipsis: { tooltip: true },
    render: (row) =>
      h(
        'button',
        {
          class: 'auction-link',
          type: 'button',
          onClick: () =>
            emit('openStock', { symbol: row.symbol, name: row.name, changePct: row.change_pct }),
        },
        row.name,
      ),
  },
  {
    title: '代码',
    key: 'code',
    width: 72,
    align: 'center',
    className: 'auction-code-col',
    render: (row) => h('span', { class: 'auction-code' }, row.code),
  },
  {
    title: '竞价价',
    key: 'price',
    width: 72,
    align: 'right',
    className: 'auction-num-col',
    render: (row) => h('span', { class: 'auction-num' }, row.price == null ? '—' : row.price.toFixed(2)),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    width: 84,
    align: 'right',
    className: 'auction-pct-col',
    render: (row) => renderPct(row.change_pct),
  },
  {
    title: '量比',
    key: 'volume_ratio',
    width: 64,
    align: 'right',
    className: 'auction-num-col',
    render: (row) =>
      h('span', { class: 'auction-num' }, row.volume_ratio == null ? '—' : row.volume_ratio.toFixed(2)),
  },
  {
    title: '竞价额',
    key: 'amount',
    width: 88,
    align: 'right',
    className: 'auction-num-col',
    render: (row) => h('span', { class: 'auction-num' }, fmtMoneyCompact(row.amount)),
  },
  {
    title: '成交量',
    key: 'volume',
    width: 80,
    align: 'right',
    className: 'auction-num-col',
    render: (row) => h('span', { class: 'auction-num' }, fmtVolume(row.volume)),
  },
  {
    title: '竞价净流入',
    key: 'open_net_inflow',
    width: 96,
    align: 'right',
    className: 'auction-num-col',
    render: (row) => h('span', { class: 'auction-num' }, fmtMoneyCompact(row.open_net_inflow)),
  },
])

watch(
  () => replayStore.tradeDate,
  (nextDate) => {
    auctionStore.setTradeDate(nextDate)
    clearPollTimer()
    scheduleNextPoll()
  },
)

watch(shouldPoll, (poll) => {
  if (poll) scheduleNextPoll()
  else clearPollTimer()
})

onMounted(() => {
  auctionStore.setTradeDate(replayStore.tradeDate)
  void auctionStore.bootstrap()
  scheduleNextPoll()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  clearPollTimer()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="auction-workspace">
    <NSpin class="auction-spin" :show="loading">
      <section class="panel-card auction-panel">
        <header class="auction-top">
          <div class="auction-title-row">
            <h2 class="panel-title">盘前竞价</h2>
            <NTag size="small" :bordered="false" class="tag-em">东财</NTag>
            <NTag v-if="phaseLabel" size="small" :type="phaseTagType" :bordered="false">
              {{ phaseLabel }}
            </NTag>
            <NTag size="small" :bordered="false">{{ tradeDate }}</NTag>
            <NTag v-if="dataKindLabel" size="small" type="info" :bordered="false">{{ dataKindLabel }}</NTag>
            <NTag v-if="sourceLabel" size="small" :bordered="false">{{ sourceLabel }}</NTag>
            <span v-if="fetchedAtLabel" class="auction-updated">更新 {{ fetchedAtLabel }}</span>
          </div>

          <div class="auction-toolbar">
            <NRadioGroup :value="sort" size="small" @update:value="onSortChange">
              <NRadioButton value="ratio">
                <span class="sort-btn"><NIcon :component="StatsChartOutline" />量比</span>
              </NRadioButton>
              <NRadioButton value="amount">
                <span class="sort-btn"><NIcon :component="CashOutline" />竞价额</span>
              </NRadioButton>
              <NRadioButton value="change">
                <span class="sort-btn"><NIcon :component="PulseOutline" />涨幅</span>
              </NRadioButton>
              <NRadioButton value="volume">成交量</NRadioButton>
              <NRadioButton value="price">价格</NRadioButton>
            </NRadioGroup>
            <span class="auction-hint">
              <NIcon :component="AlarmOutline" />
              集合竞价 09:15–09:25 · 定盘 09:25–09:30
            </span>
          </div>
        </header>

        <div class="auction-body">
          <NDataTable
            v-if="items.length"
            class="auction-table"
            size="small"
            :bordered="false"
            :single-line="false"
            :columns="columns"
            :data="items"
            :row-props="(row) => ({
              style: 'cursor: pointer',
              onClick: () => emit('openStock', {
                symbol: row.symbol,
                name: row.name,
                changePct: row.change_pct,
              }),
            })"
          />
          <NEmpty
            v-else
            class="auction-empty"
            :description="emptyDescription"
          />
        </div>
      </section>
    </NSpin>

    <p v-if="error" class="auction-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.auction-workspace {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 6px;
}

.auction-spin {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.auction-spin :deep(.n-spin-container),
.auction-spin :deep(.n-spin-content) {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.auction-panel {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  padding: 6px 8px;
  gap: 6px;
}

.auction-top {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: 6px;
}

.auction-title-row {
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

.auction-updated {
  margin-left: auto;
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
}

.auction-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.sort-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.auction-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
}

.auction-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
}

.auction-table {
  min-height: 0;
  flex: 1;
}

.auction-table :deep(.auction-code-col),
.auction-table :deep(.auction-num-col),
.auction-table :deep(.auction-pct-col) {
  white-space: nowrap;
}

.auction-link {
  border: none;
  background: none;
  padding: 0;
  font: inherit;
  color: var(--accent);
  cursor: pointer;
  text-align: left;
}

.auction-link:hover {
  text-decoration: underline;
}

.auction-code {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.auction-num {
  font-variant-numeric: tabular-nums;
}

.auction-pct {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.auction-empty {
  padding: 2rem 0;
}

.auction-error {
  flex-shrink: 0;
  margin: 0;
  padding: 0 4px;
  font-size: 12px;
  color: #ef4444;
}
</style>
