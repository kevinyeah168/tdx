<script setup lang="ts">
import { NDataTable, NEmpty, NRadioButton, NRadioGroup, NSpin, type DataTableColumns } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h, onBeforeUnmount, onMounted } from 'vue'

import type { HotBoardItem, HotStockItem } from '@/api/hotList'
import { HOT_LIST_OFF_HOURS_POLL_MS, HOT_LIST_POLL_MS } from '@/constants/refresh'
import { useHotListStore } from '@/stores/hotListStore'
import { chgTone, fmtPct, toneClass } from '@/utils/format'
import { isLiveTradingClock } from '@/utils/tradingSession'

const emit = defineEmits<{
  openStock: [target: { symbol: string; name: string; changePct?: number | null }]
  openSector: [sectorId: string]
}>()

function openStockRow(row: HotStockItem) {
  emit('openStock', { symbol: row.symbol, name: row.name, changePct: row.change_pct })
}

const hotListStore = useHotListStore()
const {
  stockBoard,
  stockSource,
  boardType,
  stockData,
  boardData,
  loading,
  error,
} = storeToRefs(hotListStore)

let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollInFlight = false

function pollIntervalMs(): number {
  return isLiveTradingClock() ? HOT_LIST_POLL_MS : HOT_LIST_OFF_HOURS_POLL_MS
}

function clearPollTimer() {
  if (pollTimer !== undefined) {
    clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

function scheduleNextPoll() {
  clearPollTimer()
  pollTimer = setTimeout(() => {
    void (async () => {
      await tickPoll()
      scheduleNextPoll()
    })()
  }, pollIntervalMs())
}

async function tickPoll() {
  if (pollInFlight || document.visibilityState === 'hidden') return
  pollInFlight = true
  try {
    await hotListStore.refresh()
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

onMounted(() => {
  void hotListStore.bootstrap()
  scheduleNextPoll()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  clearPollTimer()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

function onStockBoardChange(value: 'popularity' | 'surge') {
  hotListStore.setStockBoard(value)
}

function onStockSourceChange(value: 'eastmoney' | 'ths' | 'both') {
  hotListStore.setStockSource(value)
}

function onBoardTypeChange(value: 'concept' | 'industry') {
  hotListStore.setBoardType(value)
}

const fetchedAtLabel = computed(() => {
  const candidates = [stockData.value?.fetched_at, boardData.value?.fetched_at].filter(Boolean)
  if (!candidates.length) return ''
  const raw = candidates.sort().at(-1) ?? ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false })
})

function fmtRankChange(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value > 0) return `+${value}`
  return String(value)
}

function fmtHotValue(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`
  return value.toFixed(0)
}

function renderPct(value: number | null | undefined) {
  const tone = chgTone(value)
  return h('span', { class: ['hot-pct', toneClass(tone)] }, fmtPct(value))
}

function stockColumns(showPrice: boolean): DataTableColumns<HotStockItem> {
  const cols: DataTableColumns<HotStockItem> = [
    { title: '排名', key: 'rank', width: 48, align: 'center' },
    {
      title: '名称',
      key: 'name',
      minWidth: 72,
      ellipsis: { tooltip: true },
      render: (row) =>
        h('button', { class: 'hot-link', type: 'button', onClick: () => openStockRow(row) }, row.name),
    },
    {
      title: '代码',
      key: 'code',
      width: 72,
      minWidth: 72,
      align: 'center',
      className: 'hot-code-col',
      render: (row) => h('span', { class: 'hot-code' }, row.code),
    },
  ]
  if (showPrice) {
    cols.push({
      title: '现价',
      key: 'price',
      width: 64,
      align: 'right',
      className: 'hot-num-col',
      render: (row) => h('span', { class: 'hot-num' }, row.price == null ? '—' : row.price.toFixed(2)),
    })
  } else {
    cols.push({
      title: '热度',
      key: 'hot_value',
      width: 64,
      align: 'right',
      className: 'hot-num-col',
      render: (row) => h('span', { class: 'hot-num' }, fmtHotValue(row.hot_value)),
    })
  }
  cols.push(
    {
      title: '涨跌幅',
      key: 'change_pct',
      width: 84,
      align: 'right',
      className: 'hot-pct-col',
      render: (row) => renderPct(row.change_pct),
    },
    {
      title: stockBoard.value === 'surge' ? '排名变动' : '热度变化',
      key: 'rank_change',
      width: 64,
      align: 'center',
      className: 'hot-num-col',
      render: (row) => h('span', { class: 'hot-num' }, fmtRankChange(row.rank_change)),
    },
  )
  return cols
}

const boardColumns = computed<DataTableColumns<HotBoardItem>>(() => [
  { title: '排名', key: 'rank', width: 48, align: 'center' },
  {
    title: '板块',
    key: 'name',
    minWidth: 80,
    ellipsis: { tooltip: true },
    render: (row) =>
      h(
        'button',
        { class: 'hot-link', type: 'button', onClick: () => emit('openSector', row.board_code) },
        row.name,
      ),
  },
  {
    title: '代码',
    key: 'board_code',
    width: 72,
    minWidth: 72,
    align: 'center',
    className: 'hot-code-col',
    render: (row) => h('span', { class: 'hot-code' }, row.board_code),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    width: 84,
    align: 'right',
    className: 'hot-pct-col',
    render: (row) => renderPct(row.change_pct),
  },
  {
    title: '热度',
    key: 'hot_value',
    width: 64,
    align: 'right',
    className: 'hot-num-col',
    render: (row) => h('span', { class: 'hot-num' }, fmtHotValue(row.hot_value)),
  },
  {
    title: '排名变化',
    key: 'rank_change',
    width: 64,
    align: 'center',
    className: 'hot-num-col',
    render: (row) => h('span', { class: 'hot-num' }, fmtRankChange(row.rank_change)),
  },
])

const singleStockItems = computed(() => stockData.value?.items ?? [])
const eastmoneyItems = computed(() => stockData.value?.eastmoney ?? [])
const thsItems = computed(() => stockData.value?.ths ?? [])
const boardItems = computed(() => boardData.value?.items ?? [])

const boardTypeLabel = computed(() => (boardType.value === 'concept' ? '概念' : '行业'))

const stockBoardLabel = computed(() => (stockBoard.value === 'surge' ? '飙升' : '人气'))
</script>

<template>
  <div class="hot-list-workspace">
    <NSpin class="hot-list-spin" :show="loading">
      <div class="hot-split">
        <section class="panel-card hot-panel hot-panel-board">
          <header class="hot-panel-header">
            <h2 class="panel-title">板块热榜</h2>
            <NRadioGroup :value="boardType" size="small" @update:value="onBoardTypeChange">
              <NRadioButton value="concept">概念</NRadioButton>
              <NRadioButton value="industry">行业</NRadioButton>
            </NRadioGroup>
          </header>
          <div class="hot-panel-body">
            <div class="hot-source-pane hot-source-pane--ths">
              <header class="source-head">
                <span class="source-dot source-dot--ths" />
                <span class="source-name">同花顺</span>
                <span class="source-meta">{{ boardTypeLabel }} Top20</span>
                <div class="source-head-tail">
                  <span class="source-count">{{ boardItems.length }} 个</span>
                  <span v-if="fetchedAtLabel" class="source-time">更新 {{ fetchedAtLabel }}</span>
                </div>
              </header>
              <div class="source-table-wrap">
                <NDataTable
                  v-if="boardItems.length"
                  size="small"
                  :bordered="false"
                  flex-height
                  class="hot-table hot-table--ths"
                  :columns="boardColumns"
                  :data="boardItems"
                  :row-key="(row: HotBoardItem) => row.board_code"
                />
                <NEmpty v-else class="hot-empty" description="暂无板块热榜数据" />
              </div>
            </div>
          </div>
        </section>

        <section class="panel-card hot-panel hot-panel-stock">
          <header class="hot-panel-header">
            <h2 class="panel-title">个股热榜</h2>
            <NRadioGroup :value="stockBoard" size="small" @update:value="onStockBoardChange">
              <NRadioButton value="popularity">人气榜</NRadioButton>
              <NRadioButton value="surge">飙升榜</NRadioButton>
            </NRadioGroup>
            <NRadioGroup :value="stockSource" size="small" @update:value="onStockSourceChange">
              <NRadioButton value="both">双源对比</NRadioButton>
              <NRadioButton value="ths">同花顺</NRadioButton>
              <NRadioButton value="eastmoney">东财</NRadioButton>
            </NRadioGroup>
          </header>

          <div v-if="stockSource === 'both'" class="hot-panel-body hot-compare-body">
            <div class="hot-source-pane hot-source-pane--em">
              <header class="source-head">
                <span class="source-dot source-dot--em" />
                <span class="source-name">东方财富</span>
                <span class="source-meta">{{ stockBoardLabel }} Top100</span>
                <span class="source-count source-count--solo">{{ eastmoneyItems.length }} 只</span>
              </header>
              <div class="source-table-wrap">
                <NDataTable
                  v-if="eastmoneyItems.length"
                  size="small"
                  :bordered="false"
                  flex-height
                  class="hot-table hot-table--em"
                  :columns="stockColumns(true)"
                  :data="eastmoneyItems"
                  :row-key="(row: HotStockItem) => `${row.source}-${row.symbol}`"
                />
                <NEmpty v-else class="hot-empty" description="暂无东财数据" />
              </div>
            </div>
            <div class="hot-source-pane hot-source-pane--ths">
              <header class="source-head">
                <span class="source-dot source-dot--ths" />
                <span class="source-name">同花顺</span>
                <span class="source-meta">{{ stockBoardLabel }} Top100</span>
                <span class="source-count source-count--solo">{{ thsItems.length }} 只</span>
              </header>
              <div class="source-table-wrap">
                <NDataTable
                  v-if="thsItems.length"
                  size="small"
                  :bordered="false"
                  flex-height
                  class="hot-table hot-table--ths"
                  :columns="stockColumns(false)"
                  :data="thsItems"
                  :row-key="(row: HotStockItem) => `${row.source}-${row.symbol}`"
                />
                <NEmpty v-else class="hot-empty" description="暂无同花顺数据" />
              </div>
            </div>
          </div>

          <div v-else class="hot-panel-body">
            <div
              class="hot-source-pane"
              :class="stockSource === 'eastmoney' ? 'hot-source-pane--em' : 'hot-source-pane--ths'"
            >
              <header class="source-head">
                <span
                  class="source-dot"
                  :class="stockSource === 'eastmoney' ? 'source-dot--em' : 'source-dot--ths'"
                />
                <span class="source-name">{{ stockSource === 'eastmoney' ? '东方财富' : '同花顺' }}</span>
                <span class="source-meta">{{ stockBoardLabel }} Top100</span>
                <div class="source-head-tail">
                  <span class="source-count">{{ singleStockItems.length }} 只</span>
                  <span v-if="fetchedAtLabel" class="source-time">更新 {{ fetchedAtLabel }}</span>
                </div>
              </header>
              <div class="source-table-wrap">
                <NDataTable
                  v-if="singleStockItems.length"
                  size="small"
                  :bordered="false"
                  flex-height
                  class="hot-table"
                  :class="stockSource === 'eastmoney' ? 'hot-table--em' : 'hot-table--ths'"
                  :columns="stockColumns(stockSource === 'eastmoney')"
                  :data="singleStockItems"
                  :row-key="(row: HotStockItem) => `${row.source}-${row.symbol}`"
                />
                <NEmpty v-else class="hot-empty" description="暂无个股热榜数据" />
              </div>
            </div>
          </div>
        </section>
      </div>
    </NSpin>

    <p v-if="error" class="hot-list-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.hot-list-workspace {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 6px;
}

.hot-list-spin {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.hot-list-spin :deep(.n-spin-container),
.hot-list-spin :deep(.n-spin-content) {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.hot-split {
  display: grid;
  min-height: 0;
  flex: 1;
  grid-template-columns: minmax(360px, 42%) minmax(0, 1fr);
  gap: 6px;
}

.hot-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  padding: 8px;
}

.hot-panel-header {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.panel-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.hot-panel-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
}

.hot-table {
  min-height: 240px;
  flex: 1;
}

.hot-compare-body {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.hot-source-pane {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  border-radius: 10px;
  padding: 8px;
}

.hot-source-pane--em {
  border: 1px solid color-mix(in srgb, #f97316 30%, var(--border));
  border-top: 3px solid #f97316;
  background: color-mix(in srgb, #f97316 5%, var(--panel));
}

.hot-source-pane--ths {
  border: 1px solid color-mix(in srgb, #e11d48 30%, var(--border));
  border-top: 3px solid #e11d48;
  background: color-mix(in srgb, #e11d48 5%, var(--panel));
}

.source-head {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
}

.source-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 999px;
}

.source-dot--em {
  background: #f97316;
  box-shadow: 0 0 0 3px color-mix(in srgb, #f97316 22%, transparent);
}

.source-dot--ths {
  background: #e11d48;
  box-shadow: 0 0 0 3px color-mix(in srgb, #e11d48 22%, transparent);
}

.source-name {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.source-meta {
  font-size: 11px;
  color: var(--muted);
}

.source-head-tail {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.source-count {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.source-count--solo {
  margin-left: auto;
}

.source-time {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.source-table-wrap {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
}

:deep(.hot-table--em .n-data-table-th) {
  background: color-mix(in srgb, #f97316 8%, var(--panel)) !important;
}

:deep(.hot-table--ths .n-data-table-th) {
  background: color-mix(in srgb, #e11d48 8%, var(--panel)) !important;
}

:deep(.hot-table .n-data-table-td.hot-code-col),
:deep(.hot-table .n-data-table-th.hot-code-col) {
  white-space: nowrap;
  min-width: 72px;
}

:deep(.hot-table .n-data-table-td.hot-pct-col),
:deep(.hot-table .n-data-table-th.hot-pct-col) {
  white-space: nowrap;
}

:deep(.hot-table .n-data-table-td.hot-num-col),
:deep(.hot-table .n-data-table-th.hot-num-col) {
  white-space: nowrap;
}

:deep(.hot-code),
:deep(.hot-pct),
:deep(.hot-num) {
  display: inline-block;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  line-height: 1.2;
}

:deep(.hot-code) {
  letter-spacing: 0.02em;
}

.hot-empty {
  padding: 2rem 0;
}

.hot-list-error {
  flex-shrink: 0;
  margin: 0;
  padding: 0 4px;
  font-size: 12px;
  color: #ef4444;
}

:deep(.hot-link) {
  border: none;
  background: transparent;
  padding: 0;
  color: inherit;
  font: inherit;
  cursor: pointer;
  text-align: left;
}

:deep(.hot-link:hover) {
  color: var(--accent);
}

@media (max-width: 1100px) {
  .hot-split {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(240px, 38%) minmax(0, 1fr);
  }
}
</style>
