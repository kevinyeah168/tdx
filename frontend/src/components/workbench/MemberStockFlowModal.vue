<script setup lang="ts">
import { NEmpty, NModal, NSpin } from 'naive-ui'
import { computed, nextTick, ref, watch } from 'vue'

import StockMultiFundChart from '@/components/workbench/StockMultiFundChart.vue'
import { fetchStockFundFlowBatch, fetchStockGrayFlowBatch } from '@/api/stocks'
import type { FlowSeries } from '@/types/board'
import { attachGrayToSeries, buildStockFlowSeries } from '@/utils/stockSeries'
import { fmtMoneyCompact, fmtPct } from '@/utils/format'

const show = defineModel<boolean>('show', { required: true })

const props = defineProps<{
  symbol: string
  name: string
  tradeDate: string
  replayMinute: string
  changePct?: number | null
  cumMain?: number | null
  cumGray?: number | null
}>()

const loading = ref(false)
const error = ref('')
const soloSeries = ref<FlowSeries | null>(null)
/** Remount chart after modal enter / data load so ECharts gets non-zero size. */
const chartRenderKey = ref(0)

const modalTitle = computed(() => {
  const code = props.symbol.replace(/\u0000/g, '').trim()
  const name = props.name.replace(/\u0000/g, '').trim()
  return name ? `${name} · ${code}` : code
})

const subtitle = computed(() => {
  const parts: string[] = [props.tradeDate.replace(/-/g, '/')]
  if (props.replayMinute) parts.push(props.replayMinute)
  if (props.cumMain != null && Number.isFinite(props.cumMain)) {
    parts.push(`明盘 ${fmtMoneyCompact(props.cumMain)}`)
  }
  if (props.cumGray != null && Number.isFinite(props.cumGray)) {
    parts.push(`暗盘 ${fmtMoneyCompact(props.cumGray)}`)
  }
  if (props.changePct != null && Number.isFinite(props.changePct)) {
    parts.push(`涨幅 ${fmtPct(props.changePct)}`)
  }
  return parts.join(' · ')
})

const soloLegend = [
  { label: '明盘', color: '#2563eb' },
  { label: '暗盘', color: '#9333ea' },
  { label: '均价', color: '#d97706' },
  { label: '价格', color: '#64748b', dashed: true },
]

async function bumpChartRender() {
  await nextTick()
  chartRenderKey.value += 1
}

async function loadSeries() {
  const symbol = props.symbol.trim().toUpperCase()
  if (!symbol || !props.tradeDate) {
    soloSeries.value = null
    return
  }

  loading.value = true
  error.value = ''
  soloSeries.value = null

  try {
    const [fundBatch, grayBatch] = await Promise.all([
      fetchStockFundFlowBatch([symbol], props.tradeDate),
      fetchStockGrayFlowBatch([symbol], props.tradeDate),
    ])
    const payload = fundBatch.items.find((item) => item.symbol.toUpperCase() === symbol)
    if (!payload?.points?.length) {
      error.value = '该交易日暂无分钟资金数据'
      return
    }

    const minute = payload.latest_complete_minute || props.replayMinute
    let built = buildStockFlowSeries(
      symbol,
      props.name,
      payload.points,
      props.changePct ?? null,
      minute,
    )
    if (!built) {
      error.value = '无法构建分时曲线'
      return
    }

    const gray = grayBatch.items.find((item) => item.symbol.toUpperCase() === symbol)
    if (gray?.points?.length) {
      built = attachGrayToSeries(built, gray.points, minute)
    }
    soloSeries.value = built
    await bumpChartRender()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => [show.value, props.symbol, props.tradeDate, props.replayMinute] as const,
  ([visible]) => {
    if (visible) void loadSeries()
    else {
      soloSeries.value = null
      error.value = ''
      chartRenderKey.value = 0
    }
  },
  { immediate: true },
)

async function onModalAfterEnter() {
  if (soloSeries.value) await bumpChartRender()
}
</script>

<template>
  <NModal
    v-model:show="show"
    preset="card"
    :title="modalTitle"
    class="member-flow-modal"
    style="width: min(96vw, 980px)"
    @after-enter="onModalAfterEnter"
  >
    <p class="member-flow-sub">{{ subtitle }}</p>

    <div class="member-flow-toolbar">
      <div class="solo-legend">
        <span v-for="item in soloLegend" :key="item.label" class="solo-legend-item">
          <span
            class="solo-legend-line"
            :class="{ dashed: item.dashed }"
            :style="{
              backgroundColor: item.dashed ? 'transparent' : item.color,
              borderColor: item.color,
            }"
          />
          {{ item.label }}
        </span>
      </div>
    </div>

    <NSpin :show="loading" class="member-flow-spin">
      <StockMultiFundChart
        v-if="soloSeries"
        :key="chartRenderKey"
        mode="solo"
        :series="[]"
        :solo-series="soloSeries"
        class="member-flow-chart"
      />
      <NEmpty v-else-if="!loading" class="member-flow-empty" :description="error || '暂无数据'" />
    </NSpin>
  </NModal>
</template>

<style scoped>
.member-flow-modal :deep(.n-card) {
  max-height: min(92vh, 860px);
}

.member-flow-modal :deep(.n-card__content) {
  display: flex;
  min-height: 520px;
  flex-direction: column;
}

.member-flow-sub {
  margin: -4px 0 10px;
  font-size: 11px;
  color: var(--muted);
}

.member-flow-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.solo-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: var(--muted);
}

.solo-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.solo-legend-line {
  display: inline-block;
  width: 14px;
  height: 2px;
  border-radius: 1px;
}

.solo-legend-line.dashed {
  height: 0;
  border-top: 2px dashed;
  background: transparent !important;
}

.member-flow-spin,
.member-flow-spin :deep(.n-spin-container),
.member-flow-spin :deep(.n-spin-content) {
  display: flex;
  min-height: 480px;
  flex: 1;
  flex-direction: column;
}

.member-flow-chart {
  width: 100%;
  min-height: 480px;
  flex: 1;
}

.member-flow-empty {
  padding: 48px 0;
}
</style>
