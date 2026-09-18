<script setup lang="ts">
import { NButton, NSlider, NTag } from 'naive-ui'
import { computed } from 'vue'

import {
  useCycleReplayStore,
  type CycleReplaySpeed,
} from '@/stores/cycleReplayStore'

const store = useCycleReplayStore()

const speedOptions: CycleReplaySpeed[] = [1, 2, 4]

const sliderValue = computed({
  get: () => store.frameIndex,
  set: (value: number) => store.seekFrame(value),
})

const sliderMax = computed(() => Math.max(store.frames.length - 1, 0))
</script>

<template>
  <div class="cycle-playback-bar">
    <div class="cycle-playback-controls">
      <NButton size="tiny" quaternary :disabled="!store.frames.length" @click="store.stepPrev">
        上一帧
      </NButton>
      <NButton
        size="tiny"
        type="primary"
        :disabled="!store.frames.length || !store.fullSeries.length"
        @click="store.togglePlay"
      >
        {{ store.playing ? '暂停' : '播放' }}
      </NButton>
      <NButton size="tiny" quaternary :disabled="!store.frames.length" @click="store.stepNext">
        下一帧
      </NButton>
      <NButton size="tiny" quaternary :disabled="!store.frames.length" @click="store.resetPlayback">
        重置
      </NButton>
      <span class="cycle-playback-speed">
        <NButton
          v-for="speed in speedOptions"
          :key="speed"
          size="tiny"
          :type="store.speed === speed ? 'primary' : 'default'"
          quaternary
          @click="store.setSpeed(speed)"
        >
          {{ speed }}x
        </NButton>
      </span>
    </div>

    <div class="cycle-playback-slider-wrap">
      <NSlider
        v-model:value="sliderValue"
        class="cycle-playback-slider"
        :min="0"
        :max="sliderMax"
        :step="1"
        :disabled="!store.frames.length"
        :tooltip="false"
      />
    </div>

    <div class="cycle-playback-meta">
      <NTag size="small" :bordered="false">{{ store.cursorDate }}</NTag>
      <span class="muted">{{ store.frameLabel }} · 步进 1 交易日</span>
    </div>
  </div>
</template>

<style scoped>
.cycle-playback-bar {
  display: grid;
  grid-template-columns: auto minmax(120px, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 8px 0 0;
  border-top: 1px solid var(--border);
}

.cycle-playback-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.cycle-playback-speed {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: 2px;
}

.cycle-playback-slider-wrap {
  min-width: 0;
}

.cycle-playback-slider {
  width: 100%;
}

.cycle-playback-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  font-size: 12px;
  white-space: nowrap;
}

.muted {
  color: var(--muted);
}

@media (max-width: 960px) {
  .cycle-playback-bar {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .cycle-playback-meta {
    justify-content: space-between;
  }
}
</style>
