<script setup lang="ts">
import { NSelect } from 'naive-ui'

const model = defineModel<string[]>({ default: () => ['main'] })

const options = [
  { label: '主力', value: 'main' },
  { label: '超大', value: 'super' },
  { label: '大单', value: 'large' },
  { label: '中单', value: 'medium' },
  { label: '小单', value: 'small' },
]
</script>

<template>
  <NSelect v-model:value="model" multiple :options="options" size="small" style="min-width: 220px" />
</template>
