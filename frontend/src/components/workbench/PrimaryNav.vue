<script setup lang="ts">
const model = defineModel<'home' | 'sectors' | 'stock' | 'health' | 'settings'>({ default: 'home' })

const tabs = [
  { key: 'home' as const, label: '首页' },
  { key: 'sectors' as const, label: '板块' },
  { key: 'stock' as const, label: '个股' },
  { key: 'health' as const, label: '健康' },
  { key: 'settings' as const, label: '设置' },
]
</script>

<template>
  <nav class="primary-nav" aria-label="主导航">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      type="button"
      class="nav-tab"
      :class="{ active: model === tab.key }"
      @click="model = tab.key"
    >
      {{ tab.label }}
    </button>
  </nav>
</template>

<style scoped>
.primary-nav {
  display: flex;
  align-items: center;
  gap: 2px;
}

.nav-tab {
  height: 30px;
  padding: 0 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: color 0.12s ease, background-color 0.12s ease;
  white-space: nowrap;
}

.nav-tab:hover {
  color: var(--text);
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}

.nav-tab.active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  font-weight: 600;
}
</style>
