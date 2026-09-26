<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch } from 'vue'

import {
  fetchMarketScopeMinutes,
  MARKET_SCOPE_ORDER,
  type MarketScopeKey,
  type MarketScopeSeries,
} from '@/api/marketScopes'
import MarketScopeSparkline from '@/components/workbench/MarketScopeSparkline.vue'
import { useBoardStore } from '@/stores/boardStore'
import { useReplayStore } from '@/stores/replayStore'
import { fmtMoney } from '@/utils/format'
import { todayTradeDate } from '@/utils/tradeDate'

const SCOPE_COLORS: Record<MarketScopeKey, string> = {
  hs: '#2563eb',
  sh: '#7c3aed',
  kc: '#e11d48',
  sz: '#ea580c',
  cy: '#0891b2',
}

const boardStore = useBoardStore()
const replayStore = useReplayStore()
const { sectorViewDate, replayMinute } = storeToRefs(boardStore)

const loading = ref(false)
const items = ref<MarketScopeSeries[]>([])

const tradeDate = computed(
  () => sectorViewDate.value || boardStore.board.sector_view_date || todayTradeDate(),
)

const cutoffMinute = computed(() => {
  if (replayStore.mode === 'replay' && replayStore.minute) return replayStore.minute
  return replayMinute.value
})

const seriesByScope = computed(() => new Map(items.value.map((item) => [item.scope, item])))

function valuesForScope(scope: MarketScopeKey): (number | null)[] {
  const series = seriesByScope.value.get(scope)
  if (!series?.points.length) return []
  const points = cutoffMinute.value
    ? series.points.filter((point) => point.minute <= cutoffMinute.value!)
    : series.points
  return points.map((point) => point.main_cumulative)
}

function latestValue(scope: MarketScopeKey): number | null {
  const values = valuesForScope(scope)
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = values[index]
    if (value != null && Number.isFinite(value)) return value
  }
  return null
}

function moneyClass(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value === 0) return 'is-flat'
  return value > 0 ? 'is-up' : 'is-down'
}

async function loadMarketScopes() {
  loading.value = true
  try {
    const response = await fetchMarketScopeMinutes(tradeDate.value, {
      minute: cutoffMinute.value,
    })
    const order = new Map(MARKET_SCOPE_ORDER.map((scope, index) => [scope, index]))
    items.value = [...response.items].sort(
      (a, b) => (order.get(a.scope) ?? 99) - (order.get(b.scope) ?? 99),
    )
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadMarketScopes()
})

watch([tradeDate, cutoffMinute], () => {
  void loadMarketScopes()
})

defineExpose({ reload: loadMarketScopes })
</script>

<template>
  <section class="market-scope-panel">
    <div class="market-scope-grid" :class="{ 'is-loading': loading }">
      <article
        v-for="scope in MARKET_SCOPE_ORDER"
        :key="scope"
        class="market-scope-card"
      >
        <div class="market-scope-card-top">
          <span class="market-scope-label">{{ seriesByScope.get(scope)?.label ?? scope }}</span>
          <span class="market-scope-value" :class="moneyClass(latestValue(scope))">
            {{ latestValue(scope) != null ? fmtMoney(latestValue(scope)!) : '—' }}
          </span>
        </div>
        <MarketScopeSparkline
          :values="valuesForScope(scope)"
          :color="SCOPE_COLORS[scope]"
        />
      </article>
    </div>
  </section>
</template>

<style scoped>
.market-scope-panel {
  flex-shrink: 0;
  min-height: 92px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.market-scope-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 5px;
}

.market-scope-grid.is-loading {
  opacity: 0.72;
}

.market-scope-card {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 1px;
  min-width: 0;
  min-height: 86px;
  padding: 3px 5px 2px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--panel-elevated, #fff) 88%, transparent);
  border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
}

.market-scope-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 3px;
  min-width: 0;
  line-height: 1.2;
}

.market-scope-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-secondary, var(--muted));
}

.market-scope-value {
  font-size: 10px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.market-scope-value.is-up {
  color: var(--rise, #dc2626);
}

.market-scope-value.is-down {
  color: var(--fall, #16a34a);
}

.market-scope-value.is-flat {
  color: var(--muted);
}

@media (max-width: 1200px) {
  .market-scope-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .market-scope-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
