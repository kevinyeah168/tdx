import { computed } from 'vue'
import { useThemeStore } from '@/stores/themeStore'

export function useChartTheme() {
  const themeStore = useThemeStore()

  const colors = computed(() => {
    if (themeStore.isDark) {
      return {
        axis: '#64748b',
        axisLine: '#334155',
        splitLine: '#1e293b',
        tooltipBg: 'rgba(15, 23, 42, 0.95)',
        tooltipBorder: '#334155',
        tooltipText: '#e2e8f0',
      }
    }
    return {
      axis: '#64748b',
      axisLine: '#cbd5e1',
      splitLine: '#e2e8f0',
      tooltipBg: 'rgba(255, 255, 255, 0.96)',
      tooltipBorder: '#e2e8f0',
      tooltipText: '#0f172a',
    }
  })

  return { colors }
}
