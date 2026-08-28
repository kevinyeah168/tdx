<script setup lang="ts">
import { NCard, NDataTable, NEmpty, NSpace, NTag } from 'naive-ui'
import { computed, watch } from 'vue'

import AsyncPanel from '@/components/workbench/AsyncPanel.vue'
import StockBarsChart from '@/components/workbench/StockBarsChart.vue'
import { useReplayStore } from '@/stores/replayStore'
import { useStockStore } from '@/stores/stockStore'
import StockFundChart from '@/components/workbench/StockFundChart.vue'
import { fmtSectorType } from '@/utils/format'

const props = defineProps<{ symbol: string }>()
const emit = defineEmits<{ back: [] }>()

const stockStore = useStockStore()
const replayStore = useReplayStore()

const fundPayload = computed(() => {
  if (!stockStore.fundFlow) return null
  return {
    sector_id: props.symbol,
    latest_complete_minute: stockStore.fundFlow.latest_complete_minute,
    fund_tiers: stockStore.fundFlow.fund_tiers,
    points: stockStore.fundFlow.points,
  }
})

const sectorColumns = [
  { title: '板块', key: 'name' },
  {
    title: '类型',
    key: 'sector_type',
    render: (row: { sector_type: string }) => fmtSectorType(row.sector_type),
  },
]

watch(
  () => [props.symbol, replayStore.tradeDate] as const,
  () => {
    void stockStore.loadAll(props.symbol, replayStore.tradeDate)
  },
  { immediate: true },
)
</script>

<template>
  <NCard :title="`${symbol} · 个股工作台`" size="small">
    <template #header-extra>
      <NTag size="small" type="info" class="cursor-pointer" @click="emit('back')">返回板块</NTag>
    </template>
    <AsyncPanel :loading="stockStore.loading" :error="stockStore.error">
      <NSpace vertical size="large">
        <div v-if="stockStore.detail">
          <p class="text-lg font-semibold">{{ stockStore.detail.name }}</p>
          <p class="text-xs opacity-70">{{ stockStore.detail.market }} · {{ stockStore.detail.code }}</p>
        </div>
        <div>
          <p class="mb-2 text-sm font-medium">主力资金</p>
          <StockFundChart v-if="fundPayload?.points.length" :payload="fundPayload" :tiers="['main']" />
          <NEmpty v-else size="small" :description="stockStore.fundError || '该交易日暂无分钟资金数据'" />
        </div>
        <div>
          <p class="mb-2 text-sm font-medium">日 K</p>
          <StockBarsChart v-if="stockStore.bars?.bars.length" :payload="stockStore.bars" />
          <NEmpty v-else size="small" description="日 K 数据同步中或暂不可用" />
        </div>
        <NDataTable
          v-if="stockStore.sectors.length"
          :columns="sectorColumns"
          :data="stockStore.sectors"
          size="small"
          :bordered="false"
        />
      </NSpace>
    </AsyncPanel>
  </NCard>
</template>
