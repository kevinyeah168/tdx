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

import { useNaiveTheme } from '@/composables/useNaiveTheme'

import { useBoardStore } from '@/stores/boardStore'

import { useThemeStore } from '@/stores/themeStore'



const { naiveTheme, themeOverrides } = useNaiveTheme()

const themeStore = useThemeStore()

const boardStore = useBoardStore()



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

    await boardStore.loadBoard()

    boardStore.resetCountdown()

  }, 6000)



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
