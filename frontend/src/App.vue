<script setup lang="ts">

import { dateZhCN, zhCN } from 'naive-ui'

import {

  NConfigProvider,

  NDialogProvider,

  NMessageProvider,

} from 'naive-ui'

import { onBeforeUnmount, onMounted, watch } from 'vue'

import AppLayout from '@/components/layout/AppLayout.vue'

import TopBar from '@/components/layout/TopBar.vue'

import DashboardPage from '@/components/pages/DashboardPage.vue'

import { WORKBENCH_REFRESH_MS } from '@/constants/refresh'
import { shouldPollLiveWorkbench } from '@/utils/tradingSession'
import { todayTradeDate } from '@/utils/tradeDate'
import { useReplayStore } from '@/stores/replayStore'

import { useNaiveTheme } from '@/composables/useNaiveTheme'

import { useBoardStore } from '@/stores/boardStore'

import { useThemeStore } from '@/stores/themeStore'



const { naiveTheme, themeOverrides } = useNaiveTheme()

const themeStore = useThemeStore()

const boardStore = useBoardStore()

const replayStore = useReplayStore()



let pollTimer: ReturnType<typeof setInterval> | undefined

let tickTimer: ReturnType<typeof setInterval> | undefined



watch(

  () => themeStore.isDark,

  (dark) => {

    document.documentElement.classList.toggle('dark', dark)

  },

  { immediate: true },

)



onMounted(async () => {

  await boardStore.loadBoard()



  pollTimer = setInterval(async () => {
    if (boardStore.isPanelBusy) return
    if (
      replayStore.mode === 'live' &&
      !shouldPollLiveWorkbench({
        mode: replayStore.mode,
        tradeDate: replayStore.tradeDate || todayTradeDate(),
      })
    ) {
      return
    }
    await boardStore.loadBoard()
    boardStore.resetCountdown()
  }, WORKBENCH_REFRESH_MS)



  tickTimer = setInterval(() => {

    boardStore.tickCountdown()

  }, 1000)

})



onBeforeUnmount(() => {

  if (pollTimer) clearInterval(pollTimer)

  if (tickTimer) clearInterval(tickTimer)

})

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

        <AppLayout>

          <TopBar />

          <DashboardPage />

        </AppLayout>

      </NDialogProvider>

    </NMessageProvider>

  </NConfigProvider>

</template>
