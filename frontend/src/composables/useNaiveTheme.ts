import { computed } from 'vue'
import {
  darkTheme,
  type GlobalThemeOverrides,
  lightTheme,
} from 'naive-ui'
import { useThemeStore } from '@/stores/themeStore'

export function useNaiveTheme() {
  const themeStore = useThemeStore()

  const naiveTheme = computed(() => (themeStore.isDark ? darkTheme : lightTheme))

  const themeOverrides = computed<GlobalThemeOverrides>(() => {
    const common = {
      primaryColor: '#2563eb',
      primaryColorHover: '#3b82f6',
      primaryColorPressed: '#1d4ed8',
      primaryColorSuppl: '#dbeafe',
      borderRadius: '10px',
      fontFamily: "'DM Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif",
      fontFamilyMono: "'JetBrains Mono', 'Cascadia Code', monospace",
    }

    if (themeStore.isDark) {
      return {
        common: {
          ...common,
          primaryColor: '#3b82f6',
          bodyColor: '#0a0e17',
          cardColor: '#121a2b',
          modalColor: '#0f172a',
          popoverColor: '#121a2b',
          borderColor: '#243049',
          textColorBase: '#e8eefc',
          textColor1: '#e8eefc',
          textColor2: '#cbd5e1',
          textColor3: '#8fa0bf',
        },
        Button: {
          textColor: '#e8eefc',
          textColorTertiary: '#cbd5e1',
          textColorHover: '#ffffff',
          textColorPressed: '#e8eefc',
          textColorFocus: '#e8eefc',
          colorSecondary: '#1e293b',
          textColorSecondary: '#e2e8f0',
          colorSecondaryHover: '#243049',
          colorSecondaryPressed: '#334155',
          borderSecondary: '1px solid #334155',
        },
        Tag: {
          color: 'rgba(59, 130, 246, 0.18)',
          textColor: '#93c5fd',
          border: '1px solid rgba(59, 130, 246, 0.35)',
        },
      }
    }

    return {
      common: {
        ...common,
        bodyColor: '#f4f6fb',
        cardColor: '#ffffff',
        modalColor: '#ffffff',
        popoverColor: '#ffffff',
        borderColor: '#dbe2ef',
        textColorBase: '#0f172a',
        textColor1: '#0f172a',
        textColor2: '#334155',
        textColor3: '#64748b',
      },
      Button: {
        textColor: '#0f172a',
        textColorTertiary: '#334155',
        textColorHover: '#0f172a',
        textColorPressed: '#0f172a',
        textColorFocus: '#0f172a',
        color: '#ffffff',
        colorHover: '#f8fafc',
        colorPressed: '#f1f5f9',
        border: '1px solid #cbd5e1',
        colorSecondary: '#f1f5f9',
        textColorSecondary: '#334155',
        colorSecondaryHover: '#e2e8f0',
        colorSecondaryPressed: '#cbd5e1',
        borderSecondary: '1px solid #cbd5e1',
      },
      Tag: {
        color: '#eff6ff',
        textColor: '#1d4ed8',
        border: '1px solid #bfdbfe',
      },
    }
  })

  return { naiveTheme, themeOverrides }
}
