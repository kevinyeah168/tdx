<script setup lang="ts">
import { NTag, NTooltip } from 'naive-ui'
import { computed } from 'vue'

import type { SectorBreadthCounts } from '@/api/sectors'
import { fmtMoney, fmtPct, fmtSectorType, chgTone, toneClass } from '@/utils/format'

export type StatKind = 'limit_up' | 'limit_down' | 'up' | 'down'

const props = defineProps<{
  sectorName: string
  sectorType: string
  sectorId: string
  memberCount: number
  headerTime: string
  changePct?: number | null
  mainFlow?: number | null
  counts?: SectorBreadthCounts | null
  empty?: boolean
}>()

const emit = defineEmits<{
  openList: [kind: StatKind]
}>()

const stats = computed(() => {
  const c = props.counts
  return [
    { kind: 'limit_up' as const, label: '涨停', value: c?.limit_up ?? 0, tone: 'limit-up', hint: '点击查看涨停个股' },
    { kind: 'limit_down' as const, label: '跌停', value: c?.limit_down ?? 0, tone: 'limit-down', hint: '点击查看跌停个股' },
    { kind: 'up' as const, label: '上涨', value: c?.up ?? 0, tone: 'up', hint: '点击查看上涨个股（不含涨停）' },
    { kind: 'down' as const, label: '下跌', value: c?.down ?? 0, tone: 'down', hint: '点击查看下跌个股（不含跌停）' },
  ]
})

function onClick(kind: StatKind, value: number) {
  if (value > 0) emit('openList', kind)
}
</script>

<template>
  <div class="sector-header panel-card">
    <div class="sector-header-row">
      <!-- 左：板块名 + 元信息 -->
      <div class="sector-identity">
        <div class="sector-title-line">
          <h2 class="sector-name">{{ sectorName }}</h2>
          <NTag size="tiny" round :bordered="false" type="info">{{ fmtSectorType(sectorType) }}</NTag>
        </div>
        <p class="sector-meta">
          <span>{{ headerTime }}</span>
          <span class="dot">·</span>
          <span class="num">{{ sectorId }}</span>
          <span class="dot">·</span>
          <span>{{ memberCount }} 成分</span>
          <template v-if="counts">
            <span class="dot">·</span>
            <span>采样 {{ counts.sampled }}/{{ counts.total_members }}</span>
          </template>
        </p>
      </div>

      <!-- 中：核心指标 -->
      <div class="sector-metrics">
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
      </div>

      <!-- 右：涨跌统计 -->
      <div class="stat-row">
        <NTooltip v-for="item in stats" :key="item.kind" :disabled="empty || item.value === 0">
          <template #trigger>
            <button
              type="button"
              class="stat-chip"
              :class="[item.tone, { disabled: empty || item.value === 0 }]"
              :disabled="empty || item.value === 0"
              @click="onClick(item.kind, item.value)"
            >
              <span class="stat-chip-label">{{ item.label }}</span>
              <span class="stat-chip-value num">{{ empty ? '—' : item.value }}</span>
            </button>
          </template>
          {{ item.hint }}
        </NTooltip>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sector-header {
  padding: 0.35rem 0.75rem;
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 5%, var(--panel)), var(--panel));
}

.sector-header-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 36px;
}

.sector-identity {
  flex: 0 1 auto;
  min-width: 0;
}

.sector-title-line {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.sector-name {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sector-meta {
  margin: 0.1rem 0 0;
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sector-meta .dot {
  margin: 0 0.25rem;
  opacity: 0.55;
}

.sector-metrics {
  display: flex;
  align-items: center;
  gap: 0.75rem;
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

.stat-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-left: auto;
  flex-shrink: 0;
}

.stat-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  height: 24px;
  padding: 0 0.45rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: color-mix(in srgb, var(--panel) 94%, var(--bg));
  cursor: pointer;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.stat-chip:not(.disabled):hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
  background: color-mix(in srgb, var(--accent) 6%, var(--panel));
}

.stat-chip.disabled {
  opacity: 0.4;
  cursor: default;
}

.stat-chip-label {
  font-size: 11px;
  color: var(--muted);
}

.stat-chip-value {
  font-size: 13px;
  font-weight: 700;
}

.metric-value.is-empty {
  color: var(--muted);
  font-weight: 500;
}

.stat-chip.limit-up .stat-chip-value {
  color: var(--up);
}

.stat-chip.limit-down .stat-chip-value {
  color: var(--down);
}

.stat-chip.up .stat-chip-value {
  color: var(--up);
}

.stat-chip.down .stat-chip-value {
  color: var(--down);
}

@media (max-width: 1100px) {
  .sector-header-row {
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .stat-row {
    margin-left: 0;
    width: 100%;
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .sector-metrics {
    width: 100%;
  }

  .stat-row {
    flex-wrap: wrap;
  }
}
</style>
