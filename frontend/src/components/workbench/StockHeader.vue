<script setup lang="ts">
import { NTag } from 'naive-ui'

import { fmtMoney, fmtPct, chgTone, toneClass } from '@/utils/format'

defineProps<{
  stockName: string
  symbol: string
  market: string
  code: string
  headerTime: string
  changePct?: number | null
  mainFlow?: number | null
  grayFlow?: number | null
  price?: number | null
  empty?: boolean
}>()
</script>

<template>
  <div class="stock-header panel-card">
    <div class="stock-header-row">
      <div class="stock-identity">
        <div class="stock-title-line">
          <h2 class="stock-name">{{ stockName }}</h2>
          <NTag size="tiny" round :bordered="false" type="info">{{ symbol }}</NTag>
        </div>
        <p class="stock-meta">
          <span>{{ headerTime }}</span>
          <span class="dot">·</span>
          <span class="num">{{ market }} {{ code }}</span>
        </p>
      </div>

      <div class="stock-metrics">
        <div class="metric-item">
          <span class="metric-label">最新价</span>
          <span class="metric-value num" :class="empty ? 'is-empty' : ''">
            {{ empty || price == null ? '—' : price.toFixed(2) }}
          </span>
        </div>
        <div class="metric-divider" />
        <div class="metric-item">
          <span class="metric-label">涨跌幅</span>
          <span class="metric-value num" :class="empty ? 'is-empty' : toneClass(chgTone(changePct))">
            {{ empty ? '—' : fmtPct(changePct) }}
          </span>
        </div>
        <div class="metric-divider" />
        <div class="metric-item">
          <span class="metric-label">主力累计</span>
          <span class="metric-value num" :class="empty ? 'is-empty' : toneClass(chgTone(mainFlow))">
            {{ empty || mainFlow == null ? '—' : fmtMoney(mainFlow) }}
          </span>
        </div>
        <div class="metric-divider" />
        <div class="metric-item">
          <span class="metric-label">暗盘累计</span>
          <span class="metric-value num" :class="empty ? 'is-empty' : toneClass(chgTone(grayFlow))">
            {{ empty || grayFlow == null ? '—' : fmtMoney(grayFlow) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stock-header {
  padding: 0.35rem 0.75rem;
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 5%, var(--panel)), var(--panel));
}

.stock-header-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 36px;
}

.stock-identity {
  flex: 0 1 auto;
  min-width: 0;
}

.stock-title-line {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.stock-name {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-meta {
  margin: 0.1rem 0 0;
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-meta .dot {
  margin: 0 0.25rem;
  opacity: 0.55;
}

.stock-metrics {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-left: auto;
  flex-shrink: 0;
}

.metric-item {
  display: flex;
  align-items: baseline;
  gap: 0.35rem;
}

.metric-label {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.metric-value {
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
}

.metric-divider {
  width: 1px;
  height: 20px;
  background: var(--border);
}

.metric-value.is-empty {
  color: var(--muted);
  font-weight: 500;
}

@media (max-width: 960px) {
  .stock-header-row {
    flex-wrap: wrap;
  }

  .stock-metrics {
    margin-left: 0;
    width: 100%;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .metric-divider {
    display: none;
  }
}
</style>
