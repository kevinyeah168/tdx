<script setup lang="ts">
import { NAlert, NEmpty, NSpin } from 'naive-ui'

defineProps<{
  loading?: boolean
  error?: string
  empty?: boolean
  emptyText?: string
}>()
</script>

<template>
  <NSpin :show="loading">
    <NAlert v-if="error" type="error" :title="error" class="mb-3" />
    <slot v-if="!empty" />
    <NEmpty v-else :description="emptyText ?? '暂无数据'" />
  </NSpin>
</template>
