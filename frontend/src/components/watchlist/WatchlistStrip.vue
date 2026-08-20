<script setup lang="ts">
import { NScrollbar, NTag } from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import { chgTone, fmtMoney, fmtPct, toneClass } from '@/utils/format'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const { board, highlightedSector, highlightedStock } = storeToRefs(boardStore)

const title = computed(() =>
  props.mode === 'stock' ? '自选个股' : '自选板块',
)

const modeLabel = computed(() =>
  props.mode === 'stock' ? boardStore.stockModeLabel : boardStore.sectorModeLabel,
)

const highlighted = computed(() =>
  props.mode === 'stock' ? highlightedStock.value : highlightedSector.value,
)

const chips = computed(() => {
  if (props.mode === 'stock') {
    return (board.value.watchlist || []).map((w) => ({
      id: w.symbol,
      name: w.name || w.symbol,
      sub: w.symbol,
      change_pct: w.quote?.change_pct,
      cum_main: w.cum_main ?? w.cum_net,
    }))
  }
  return (board.value.sector_series || []).map((s) => ({
    id: s.id,
    name: s.name,
    sub: s.id,
    change_pct: s.change_pct,
    cum_main: s.cum_main,
  }))
})

function onChipClick(id: string) {
  boardStore.toggleHighlight(id, props.mode)
}
</script>

<template>
  <section class="panel-card p-2.5">
    <div class="mb-2 flex items-center justify-between gap-2 border-b border-[var(--border)] pb-1.5">
      <h3 class="m-0 text-xs font-600">{{ title }}</h3>
      <span class="text-[10px] text-[var(--muted)]">{{ modeLabel }} · 点击高亮</span>
    </div>

    <NScrollbar x-scrollable>
      <div class="flex gap-1.5 pb-0.5">
        <button
          v-for="c in chips"
          :key="c.id"
          type="button"
          class="watch-chip shrink-0"
          :class="{ active: highlighted === c.id }"
          @click="onChipClick(c.id)"
        >
          <span class="chip-name">{{ c.name }}</span>
          <span class="num text-[10px] text-[var(--muted)]">{{ c.sub }}</span>
          <span class="num text-[11px]" :class="toneClass(chgTone(c.change_pct))">
            {{ fmtPct(c.change_pct) }}
          </span>
          <span class="num text-[11px]" :class="toneClass(chgTone(c.cum_main))">
            {{ fmtMoney(c.cum_main) }}
          </span>
        </button>

        <NTag v-if="!chips.length" size="small">
          {{ mode === 'stock' ? '点击顶栏「自选个股」添加' : '点击顶栏「自选板块」添加' }}
        </NTag>
      </div>
    </NScrollbar>
  </section>
</template>

<style scoped>
.watch-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 92%, var(--bg));
  color: var(--text);
  font-size: 11px;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.chip-name {
  font-size: 12px;
  font-weight: 600;
  max-width: 5em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.watch-chip:hover {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  background: color-mix(in srgb, var(--accent) 6%, var(--panel));
}

.watch-chip.active {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
}
</style>
