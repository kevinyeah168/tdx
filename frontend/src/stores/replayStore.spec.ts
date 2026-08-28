import { describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useReplayStore } from '@/stores/replayStore'

describe('replayStore', () => {
  it('switches between live and replay modes', () => {
    setActivePinia(createPinia())
    const store = useReplayStore()
    store.setReplay('2026-08-20', '09:31')
    expect(store.mode).toBe('replay')
    store.setLive()
    expect(store.mode).toBe('live')
  })
})
