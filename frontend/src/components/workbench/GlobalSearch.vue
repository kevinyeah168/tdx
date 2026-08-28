<script setup lang="ts">
import { NAutoComplete } from 'naive-ui'
import { ref } from 'vue'

import { apiGet } from '@/api/client'
import type { SearchResponse } from '@/types/api'

const emit = defineEmits<{
  select: [symbol: string]
}>()

const query = ref('')
const options = ref<{ label: string; value: string }[]>([])

async function search(value: string) {
  query.value = value
  if (!value.trim()) {
    options.value = []
    return
  }
  const response = await apiGet<SearchResponse>('/api/v1/market/search', { q: value })
  options.value = response.results.map((item) => ({
    label: `${item.symbol} ${item.name}`,
    value: item.symbol,
  }))
}

function onSelect(symbol: string) {
  emit('select', symbol)
}
</script>

<template>
  <NAutoComplete
    v-model:value="query"
    class="global-search"
    :options="options"
    placeholder="搜索代码或名称"
    clearable
    size="small"
    @update:value="search"
    @select="onSelect"
  />
</template>

<style scoped>
.global-search {
  width: 168px;
}
</style>
