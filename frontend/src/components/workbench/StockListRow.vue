<script setup lang="ts">
import { NCheckbox } from 'naive-ui'

import type { StockListItem } from '@/stores/stockStore'
import { fmtMoneyCompact, fmtPct, chgTone, toneClass } from '@/utils/format'

defineProps<{
  item: StockListItem
  chartSelected: boolean
  chartColor?: string
  focused: boolean
}>()

const emit = defineEmits<{
  toggle: [checked: boolean]
  focus: []
}>()
</script>

<template>
  <div
    class="stock-item"
    :class="{
      'is-chart': chartSelected,
      'is-focus': focused,
    }"
    :style="chartSelected && chartColor ? { '--chart-color': chartColor } : undefined"
    @click="emit('focus')"
  >
    <NCheckbox
      :checked="chartSelected"
      @update:checked="(checked) => emit('toggle', checked)"
      @click.stop
    />
    <div class="stock-item-main">
      <span class="stock-name">{{ item.name }}</span>
      <span class="stock-symbol num">{{ item.symbol }}</span>
    </div>
    <div class="stock-item-metrics num">
      <span :class="toneClass(chgTone(item.main_cumulative))">
        {{ fmtMoneyCompact(item.main_cumulative) }}
      </span>
      <span :class="toneClass(chgTone(item.change_pct))">
        {{ fmtPct(item.change_pct) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.stock-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  height: 54px;
  padding: 0 10px 0 8px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 55%, transparent);
  cursor: pointer;
  color: var(--text);
  transition: background-color 0.12s ease, box-shadow 0.12s ease;
}

.stock-item:hover {
  background: color-mix(in srgb, var(--accent) 6%, var(--panel));
}

.stock-item.is-chart {
  background: color-mix(in srgb, var(--chart-color, var(--accent)) 10%, var(--panel));
  box-shadow: inset 3px 0 0 var(--chart-color, var(--accent));
}

.stock-item.is-focus {
  background: color-mix(in srgb, var(--accent) 8%, var(--panel));
}

.stock-item.is-chart.is-focus {
  background: color-mix(in srgb, var(--chart-color, var(--accent)) 14%, var(--panel));
}

.stock-item-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.stock-name {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-symbol {
  font-size: 10px;
  color: var(--muted);
}

.stock-item-metrics {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: 11px;
  white-space: nowrap;
}
</style>
