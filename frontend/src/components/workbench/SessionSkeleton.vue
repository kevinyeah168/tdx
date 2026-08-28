<script setup lang="ts">
defineProps<{
  tradeDate: string
  title?: string
  message?: string
}>()
</script>

<template>
  <div class="session-skeleton panel-card">
    <div class="skeleton-chart" />
    <div class="skeleton-overlay">
      <p class="skeleton-title">{{ title || '今日暂无行情数据' }}</p>
      <p class="skeleton-msg">
        {{
          message ||
            `${tradeDate} 尚未采集到完整分钟数据。开盘后将自动更新；也可在顶部选择已有数据的交易日进行回放。`
        }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.session-skeleton {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: color-mix(in srgb, var(--panel) 96%, var(--bg));
  border-radius: 8px;
}

.skeleton-chart {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--border) 28%, transparent) 0%,
    color-mix(in srgb, var(--border) 12%, transparent) 50%,
    color-mix(in srgb, var(--border) 28%, transparent) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.6s ease-in-out infinite;
}

.skeleton-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 24px;
  text-align: center;
  background: color-mix(in srgb, var(--panel) 55%, transparent);
}

.skeleton-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.skeleton-msg {
  margin: 0;
  max-width: 360px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--muted);
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
