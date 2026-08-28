<script setup lang="ts">
import { MoonOutline, RefreshOutline, SunnyOutline } from '@vicons/ionicons5'
import { NButton, NDropdown, NIcon, NSpace, NTag, NTooltip } from 'naive-ui'
import { computed } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import { useThemeStore, type ThemeMode } from '@/stores/themeStore'

const boardStore = useBoardStore()
const themeStore = useThemeStore()

const themeLabel = computed(() => {
  if (themeStore.mode === 'system') return '跟随系统'
  return themeStore.isDark ? '深色' : '浅色'
})

const themeOptions = [
  { label: '浅色', key: 'light' },
  { label: '深色', key: 'dark' },
  { label: '跟随系统', key: 'system' },
]

function onThemeSelect(key: string) {
  themeStore.setMode(key as ThemeMode)
}

const themeIcon = computed(() =>
  themeStore.isDark ? MoonOutline : SunnyOutline,
)
</script>

<template>
  <header class="mb-3 flex items-center justify-between gap-4 px-1">
    <h1 class="m-0 text-lg font-700 tracking-tight text-[var(--text)] lg:text-xl">
      板块脉搏
    </h1>

    <NSpace align="center" :size="8" class="shrink-0">
      <NButton size="small" @click="boardStore.openPicker">
        自选板块
      </NButton>
      <NButton size="small" @click="boardStore.openStockPicker">
        自选个股
      </NButton>

      <NTag round size="small" type="info">
        <span class="num">{{ boardStore.countdown }}s</span>
      </NTag>

      <NDropdown trigger="click" :options="themeOptions" @select="onThemeSelect">
        <NTooltip>
          <template #trigger>
            <NButton quaternary circle size="small" :title="`主题：${themeLabel}`">
              <template #icon>
                <NIcon :component="themeIcon" />
              </template>
            </NButton>
          </template>
          主题：{{ themeLabel }}
        </NTooltip>
      </NDropdown>

      <NButton
        type="primary"
        size="small"
        :loading="boardStore.loading"
        @click="boardStore.manualRefresh"
      >
        <template #icon>
          <NIcon :component="RefreshOutline" />
        </template>
        刷新
      </NButton>
    </NSpace>
  </header>

  <NTag
    v-if="boardStore.board.error"
    type="error"
    size="small"
    class="mb-3 w-full"
  >
    {{ boardStore.board.error }}
  </NTag>
</template>
