import { useLocalStorage, usePreferredDark } from '@vueuse/core'
import { computed } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark' | 'system'

export const useThemeStore = defineStore('theme', () => {
  const mode = useLocalStorage<ThemeMode>('tdx-theme-mode-v2', 'light')
  const preferredDark = usePreferredDark()

  const isDark = computed(() => {
    if (mode.value === 'system') return preferredDark.value
    return mode.value === 'dark'
  })

  function setMode(next: ThemeMode) {
    mode.value = next
  }

  function toggle() {
    mode.value = isDark.value ? 'light' : 'dark'
  }

  return { mode, isDark, setMode, toggle }
})
