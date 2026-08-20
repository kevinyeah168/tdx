<script setup lang="ts">
import MarketPanel from '@/components/pages/MarketPanel.vue'
import SectorPickerDrawer from '@/components/sector/SectorPickerDrawer.vue'
import StockPickerDrawer from '@/components/stock/StockPickerDrawer.vue'
</script>

<template>
  <div class="grid h-[calc(100vh-72px)] min-h-[640px] grid-cols-2 gap-3">
    <div class="panel-card flex min-h-0 flex-col p-3">
      <MarketPanel mode="sector" />
    </div>
    <div class="panel-card flex min-h-0 flex-col p-3">
      <MarketPanel mode="stock" />
    </div>
    <SectorPickerDrawer />
    <StockPickerDrawer />
  </div>
</template>
