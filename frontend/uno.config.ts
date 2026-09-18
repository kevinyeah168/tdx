import {
  defineConfig,
  presetAttributify,
  presetIcons,
  presetUno,
  transformerDirectives,
} from 'unocss'

export default defineConfig({
  presets: [presetUno(), presetAttributify(), presetIcons()],
  transformers: [transformerDirectives()],
  shortcuts: {
    'num': 'font-mono tabular-nums',
    'text-up': 'text-[var(--up)]',
    'text-down': 'text-[var(--down)]',
    'text-flat': 'text-[var(--muted)]',
  },
  theme: {
    colors: {
      up: 'var(--up)',
      down: 'var(--down)',
    },
  },
})
