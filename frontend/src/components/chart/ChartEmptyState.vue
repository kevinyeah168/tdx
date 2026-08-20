<script setup lang="ts">
defineProps<{
  title?: string
  message?: string
}>()
</script>

<template>
  <div class="chart-empty absolute inset-0 flex flex-col items-center justify-center gap-3 px-6">
    <div class="skeleton-grid w-full max-w-[92%] flex-1 min-h-[120px] rounded-lg" />
    <div class="text-center">
      <p class="m-0 text-sm font-600 text-[var(--text)]">
        {{ title || '尚未开盘' }}
      </p>
      <p class="mt-1 mb-0 text-xs text-[var(--muted)] leading-relaxed max-w-[280px]">
        {{ message || '今日尚未开盘，数据在交易日 09:31 开始实时更新' }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.chart-empty {
  background: color-mix(in srgb, var(--panel) 88%, var(--bg));
}

.skeleton-grid {
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--border) 35%, transparent) 0%,
    color-mix(in srgb, var(--border) 18%, transparent) 50%,
    color-mix(in srgb, var(--border) 35%, transparent) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.6s ease-in-out infinite;
}

@keyframes shimmer {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}
</style>
