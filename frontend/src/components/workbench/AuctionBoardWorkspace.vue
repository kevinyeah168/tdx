<script setup lang="ts">
import { AlarmOutline, SearchOutline } from '@vicons/ionicons5'
import {
  NDataTable,
  NEmpty,
  NIcon,
  NInput,
  NPagination,
  NRadioButton,
  NRadioGroup,
  NSpin,
  NTag,
  type DataTableColumns,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { AuctionBoardItem, AuctionBoardScope } from '@/api/auctionBoard'
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
const {
  data,
  loading,
  refreshing,
  error,
  tradeDate,
  shouldPoll,
  scope,
  searchQuery,
  page,
  pageSize,
  total,
} = storeToRefs(auctionStore)

let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollInFlight = false
let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined
const searchInput = ref(searchQuery.value)

const items = computed(() => data.value?.items ?? [])
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const rangeStart = computed(() => (total.value === 0 ? 0 : (page.value - 1) * pageSize.value + 1))
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, total.value))
const showPagination = computed(() => scope.value === 'market' && total.value > pageSize.value)
const isLiveAuction = computed(() => data.value?.phase === 'auction' || data.value?.phase === 'post_auction')
const showBlockingSpin = computed(() => loading.value && !data.value)

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
  if (data.value?.phase === 'waiting' && scope.value === 'market') {
    return '竞价尚未开始（09:15），全市场数据 09:15 后开放'
  }
  if (data.value?.phase === 'waiting') return '竞价尚未开始（09:15）'
  if (data.value?.phase === 'auction') return '竞价进行中，东财榜单拉取中…（若持续为空请点刷新）'
  if (data.value?.phase === 'post_auction') return '已定盘，榜单数据写入中…'
  if (data.value?.phase === 'closed' && data.value?.data_kind !== 'snapshot') {
    return '竞价已结束，暂无当日快照（Collector 于 09:26/09:29 自动采集；可点刷新尝试补拉）'
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
  const pollMs =
    items.value.length === 0 && shouldPoll.value ? AUCTION_POLL_MS * 2 : AUCTION_POLL_MS
  pollTimer = setTimeout(() => {
    void (async () => {
      await tickPoll()
      scheduleNextPoll()
    })()
  }, pollMs)
}

async function tickPoll() {
  if (!shouldPoll.value || pollInFlight || document.visibilityState === 'hidden') return
  pollInFlight = true
  try {
    await auctionStore.refresh({ silent: true })
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

function fmtVolume(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万手`
  return `${value.toFixed(0)}手`
}

function numSorter(get: (row: AuctionBoardItem) => number | null | undefined) {
  return (a: AuctionBoardItem, b: AuctionBoardItem) => {
    const av = get(a)
    const bv = get(b)
    if (av == null && bv == null) return 0
    if (av == null) return -1
    if (bv == null) return 1
    return av - bv
  }
}

function renderPct(value: number | null | undefined) {
  const tone = chgTone(value)
  return h('span', { class: ['auction-pct', toneClass(tone)] }, fmtPct(value))
}

function renderStockCell(row: AuctionBoardItem) {
  return h(
    'button',
    {
      class: 'auction-stock-cell',
      type: 'button',
      onClick: () => emit('openStock', { symbol: row.symbol, name: row.name, changePct: row.change_pct }),
    },
    [
      h('span', { class: 'auction-stock-name' }, row.name),
      h('span', { class: 'auction-stock-code' }, row.code),
    ],
  )
}

const showMatchPrice = computed(() => items.value.some((row) => row.price != null && Number.isFinite(row.price)))
const showAuctionAmount = computed(() =>
  items.value.some((row) => row.amount != null && Number.isFinite(row.amount) && row.amount !== 0),
)
const showNetInflow = computed(() =>
  items.value.some((row) => row.open_net_inflow != null && Number.isFinite(row.open_net_inflow) && row.open_net_inflow !== 0),
)

const tableScrollX = computed(() => {
  let width = 40 + 128 + 72 + 64 + 72 // # + 标的 + 涨跌幅 + 量比 + 成交量
  if (showMatchPrice.value) width += 64
  if (showAuctionAmount.value) width += 76
  if (showNetInflow.value) width += 84
  return width
})

const columns = computed<DataTableColumns<AuctionBoardItem>>(() => {
  const cols: DataTableColumns<AuctionBoardItem> = [
    {
      title: '#',
      key: 'rank',
      width: 40,
      align: 'center',
      className: 'auction-idx-col',
      render: (row) => h('span', { class: 'auction-idx' }, String(row.rank)),
    },
    {
      title: '标的',
      key: 'name',
      width: 128,
      className: 'auction-stock-col',
      render: (row) => renderStockCell(row),
    },
    {
      title: '涨跌幅',
      key: 'change_pct',
      width: 72,
      align: 'right',
      className: 'auction-pct-col',
      sorter: numSorter((row) => row.change_pct),
      render: (row) => renderPct(row.change_pct),
    },
    {
      title: '量比',
      key: 'volume_ratio',
      width: 64,
      align: 'right',
      className: 'auction-num-col auction-sort-default',
      sorter: numSorter((row) => row.volume_ratio),
      defaultSortOrder: 'descend',
      render: (row) =>
        h('span', { class: 'auction-num' }, row.volume_ratio == null ? '—' : row.volume_ratio.toFixed(2)),
    },
  ]

  if (showMatchPrice.value) {
    cols.push({
      title: '匹配价',
      key: 'price',
      width: 64,
      align: 'right',
      className: 'auction-num-col',
      sorter: numSorter((row) => row.price),
      render: (row) => h('span', { class: 'auction-num' }, row.price == null ? '—' : row.price.toFixed(2)),
    })
  }

  if (showAuctionAmount.value) {
    cols.push({
      title: '竞价额',
      key: 'amount',
      width: 76,
      align: 'right',
      className: 'auction-num-col',
      sorter: numSorter((row) => row.amount),
      render: (row) => h('span', { class: 'auction-num' }, fmtMoneyCompact(row.amount)),
    })
  }

  cols.push({
    title: '成交量',
    key: 'volume',
    width: 72,
    align: 'right',
    className: 'auction-num-col',
    sorter: numSorter((row) => row.volume),
    render: (row) => h('span', { class: 'auction-num' }, fmtVolume(row.volume)),
  })

  if (showNetInflow.value) {
    cols.push({
      title: '净流入',
      key: 'open_net_inflow',
      width: 84,
      align: 'right',
      className: 'auction-num-col',
      sorter: numSorter((row) => row.open_net_inflow),
      render: (row) => h('span', { class: 'auction-num' }, fmtMoneyCompact(row.open_net_inflow)),
    })
  }

  return cols
})

function onSearchInput(value: string) {
  searchInput.value = value
  if (searchDebounceTimer !== undefined) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    auctionStore.setSearchQuery(value.trim())
  }, 300)
}

function onScopeChange(nextScope: AuctionBoardScope) {
  auctionStore.setScope(nextScope)
}

function onPageChange(nextPage: number) {
  auctionStore.setPage(nextPage)
}

watch(
  () => replayStore.tradeDate,
  (nextDate) => {
    auctionStore.setTradeDate(nextDate)
    clearPollTimer()
    scheduleNextPoll()
  },
)

watch(searchQuery, (value) => {
  if (value !== searchInput.value) {
    searchInput.value = value
  }
})

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
  if (searchDebounceTimer !== undefined) clearTimeout(searchDebounceTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="auction-workspace">
    <NSpin class="auction-spin" :show="showBlockingSpin">
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
            <span v-if="refreshing" class="auction-syncing">同步中…</span>
            <span v-if="fetchedAtLabel" class="auction-updated">更新 {{ fetchedAtLabel }}</span>
          </div>

          <div class="auction-toolbar">
            <div class="auction-toolbar-main">
              <NInput
                class="auction-search"
                size="small"
                clearable
                :value="searchInput"
                placeholder="搜索代码或名称"
                @update:value="onSearchInput"
              >
                <template #prefix>
                  <NIcon :component="SearchOutline" />
                </template>
              </NInput>

              <NRadioGroup
                class="auction-scope-group"
                :value="scope"
                size="small"
                @update:value="onScopeChange"
              >
                <NRadioButton value="top">快速榜 Top100</NRadioButton>
                <NRadioButton value="market">全市场</NRadioButton>
              </NRadioGroup>

              <span v-if="total > 0" class="auction-count">
                共 <strong>{{ total.toLocaleString('zh-CN') }}</strong> 只
              </span>
            </div>

            <p class="auction-hint">
              <NIcon :component="AlarmOutline" />
              <span>09:15–09:25 竞价</span>
              <span v-if="scope === 'market'" class="auction-hint-sep">·</span>
              <span v-if="scope === 'market'">全市场首次加载约 30–60s</span>
              <span v-if="scope === 'top'" class="auction-hint-sep">·</span>
              <span v-if="scope === 'top'">仅 Top100，更多请切换全市场</span>
            </p>
          </div>
        </header>

        <div class="auction-body">
          <div v-if="items.length" class="auction-table-wrap">
            <div class="auction-table-scroll">
              <NDataTable
                class="auction-table"
                size="small"
                flex-height
                :bordered="false"
                :single-line="false"
                :scroll-x="tableScrollX"
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
            </div>
            <footer v-if="showPagination" class="auction-pagination-bar">
              <div class="auction-pagination-info">
                <span class="auction-pagination-range">
                  第
                  <strong>{{ rangeStart.toLocaleString('zh-CN') }}</strong>
                  –
                  <strong>{{ rangeEnd.toLocaleString('zh-CN') }}</strong>
                  条
                </span>
                <span class="auction-pagination-total">
                  共 {{ total.toLocaleString('zh-CN') }} 只
                </span>
                <span v-if="searchQuery.trim()" class="auction-pagination-filter">已筛选</span>
              </div>
              <NPagination
                class="auction-pagination-control"
                size="medium"
                :page="page"
                :page-count="pageCount"
                :page-size="pageSize"
                :page-slot="7"
                show-quick-jumper
                @update:page="onPageChange"
              />
            </footer>
          </div>
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
  gap: 4px;
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

.auction-syncing {
  font-size: 10px;
  color: var(--accent);
  white-space: nowrap;
}

.auction-updated {
  margin-left: auto;
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
}

.auction-toolbar {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.auction-toolbar-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.auction-search {
  width: 200px;
  flex-shrink: 0;
}

.auction-scope-group {
  flex-shrink: 0;
}

.auction-count {
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.auction-count strong {
  color: var(--text);
  font-weight: 700;
}

.auction-hint {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  margin: 0;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
}

.auction-hint-sep {
  opacity: 0.5;
}

.auction-body {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
}

.auction-table-wrap {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--panel) 96%, var(--accent) 4%);
}

.auction-table-scroll {
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

.auction-pagination-bar {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-top: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
  background: color-mix(in srgb, var(--accent) 6%, var(--panel));
}

.auction-pagination-info {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.auction-pagination-range strong,
.auction-pagination-total {
  color: var(--text);
  font-weight: 600;
}

.auction-pagination-filter {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
}

.auction-pagination-control {
  margin-left: auto;
}

.auction-pagination-control :deep(.n-pagination-item) {
  min-width: 34px;
  height: 34px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 8px;
}

.auction-pagination-control :deep(.n-pagination-item--active) {
  background: var(--accent) !important;
  color: #fff !important;
  font-weight: 700;
  box-shadow: 0 1px 4px color-mix(in srgb, var(--accent) 35%, transparent);
}

.auction-pagination-control :deep(.n-pagination-quick-jumper) {
  font-size: 12px;
}

.auction-table :deep(.n-data-table-table) {
  table-layout: fixed;
}

.auction-table :deep(.auction-idx-col),
.auction-table :deep(.auction-num-col),
.auction-table :deep(.auction-pct-col) {
  white-space: nowrap;
}

.auction-table :deep(.auction-stock-col) {
  overflow: hidden;
}

.auction-table :deep(.auction-sort-default .n-data-table-th__title) {
  color: var(--accent);
  font-weight: 600;
}

.auction-idx {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.auction-stock-cell {
  display: inline-flex;
  max-width: 100%;
  min-width: 0;
  align-items: baseline;
  gap: 6px;
  border: none;
  background: none;
  padding: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.auction-stock-name {
  flex-shrink: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.auction-stock-code {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  opacity: 0.9;
}

.auction-stock-cell:hover .auction-stock-name {
  color: var(--accent);
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
