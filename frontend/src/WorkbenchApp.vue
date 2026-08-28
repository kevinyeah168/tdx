<script setup lang="ts">
import { dateZhCN, zhCN } from 'naive-ui'
import { NConfigProvider, NDialogProvider, NMessageProvider } from 'naive-ui'
import { watch } from 'vue'

import WorkbenchShell from '@/components/workbench/WorkbenchShell.vue'
import { useNaiveTheme } from '@/composables/useNaiveTheme'
import { useThemeStore } from '@/stores/themeStore'

const { naiveTheme, themeOverrides } = useNaiveTheme()
const themeStore = useThemeStore()

watch(
  () => themeStore.isDark,
  (dark) => {
    document.documentElement.classList.toggle('dark', dark)
  },
  { immediate: true },
)
</script>

<template>
  <NConfigProvider
    :theme="naiveTheme"
    :theme-overrides="themeOverrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <NMessageProvider>
      <NDialogProvider>
        <WorkbenchShell />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
