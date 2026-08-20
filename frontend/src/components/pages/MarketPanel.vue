<script setup lang="ts">
import FundFlowChart from '@/components/chart/FundFlowChart.vue'
import FundRankPanel from '@/components/common/FundRankPanel.vue'
import IntradayDatePicker from '@/components/common/IntradayDatePicker.vue'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useBoardStore } from '@/stores/boardStore'

const props = defineProps<{
  mode: 'sector' | 'stock'
}>()

const boardStore = useBoardStore()
const { board } = storeToRefs(boardStore)

const title = computed(() => (props.mode === 'stock' ? '个股主力' : '板块主力'))
const count = computed(() =>
  props.mode === 'stock'
    ? board.value.stock_series?.length ?? 0
    : board.value.sector_series?.length ?? 0,
)
</script>

<template>
  <section class="flex h-full min-h-0 flex-col gap-2">
    <div class="flex shrink-0 items-center justify-between gap-2 px-1">
      <div class="flex min-w-0 items-center gap-2">
        <h2 class="m-0 text-sm font-600 text-[var(--text)]">{{ title }}</h2>
        <span class="text-xs text-[var(--muted)]">({{ count }})</span>
      </div>
      <IntradayDatePicker :mode="mode" />
    </div>

    <div class="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_248px] gap-2">
      <FundFlowChart :mode="mode" />
      <FundRankPanel :mode="mode" />
    </div>
  </section>
</template>
