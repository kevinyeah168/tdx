import { defineStore } from 'pinia'

import { fetchReplayDates } from '@/api/replay'
import { todayTradeDate } from '@/utils/tradeDate'

export const useReplayStore = defineStore('replay', {
  state: () => ({
    mode: 'live' as 'live' | 'replay',
    tradeDate: todayTradeDate(),
    minute: '09:31',
    playing: false,
    availableDates: [] as string[],
  }),
  getters: {
    isToday(state): boolean {
      return state.tradeDate === todayTradeDate()
    },
  },
  actions: {
    async loadAvailableDates() {
      const response = await fetchReplayDates()
      this.availableDates = response.dates
    },
    setLive() {
      this.mode = 'live'
      this.playing = false
      this.tradeDate = todayTradeDate()
    },
    setReplay(tradeDate: string, minute: string) {
      this.mode = tradeDate === todayTradeDate() ? 'live' : 'replay'
      this.tradeDate = tradeDate
      this.minute = minute
    },
  },
})
