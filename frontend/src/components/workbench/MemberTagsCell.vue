<script setup lang="ts">
import { NModal, NTag, NTooltip } from 'naive-ui'
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    names: string[]
    maxVisible?: number
    modalTitle?: string
  }>(),
  {
    maxVisible: 5,
    modalTitle: '全部成员',
  },
)

const showAll = ref(false)

const cleaned = computed(() => props.names.map((name) => name.trim()).filter(Boolean))
const visibleNames = computed(() => cleaned.value.slice(0, props.maxVisible))
const hiddenCount = computed(() => Math.max(0, cleaned.value.length - props.maxVisible))
</script>

<template>
  <div class="member-tags-cell">
    <span v-if="!cleaned.length" class="member-tags-empty">—</span>
    <div v-else class="member-tags-row">
      <NTag
        v-for="name in visibleNames"
        :key="name"
        size="small"
        :bordered="false"
        round
        class="member-tag"
      >
        {{ name }}
      </NTag>
      <NTooltip v-if="hiddenCount > 0" trigger="hover">
        <template #trigger>
          <button type="button" class="member-tags-more" @click="showAll = true">
            <span class="member-tags-more-dots" aria-hidden="true">···</span>
            <span class="member-tags-more-text">+{{ hiddenCount }}</span>
          </button>
        </template>
        查看全部 {{ cleaned.length }} 个
      </NTooltip>
    </div>

    <NModal
      v-model:show="showAll"
      preset="card"
      :title="modalTitle"
      class="member-tags-modal"
      :style="{ width: '520px', maxWidth: '92vw' }"
    >
      <p class="member-tags-count">共 {{ cleaned.length }} 个</p>
      <div class="member-tags-all">
        <NTag
          v-for="name in cleaned"
          :key="name"
          size="small"
          :bordered="false"
          round
          class="member-tag"
        >
          {{ name }}
        </NTag>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.member-tags-cell {
  padding: 2px 0;
}

.member-tags-empty {
  color: var(--muted);
}

.member-tags-row,
.member-tags-all {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.member-tag {
  max-width: 140px;
}

.member-tag :deep(.n-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-tags-more {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  height: 22px;
  padding: 0 8px;
  border: 1px dashed color-mix(in srgb, var(--accent) 28%, var(--border));
  border-radius: 11px;
  background: color-mix(in srgb, var(--accent) 6%, var(--panel));
  color: var(--accent);
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease,
    transform 0.15s ease;
}

.member-tags-more:hover {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
}

.member-tags-more:active {
  transform: scale(0.97);
}

.member-tags-more-dots {
  font-size: 10px;
  letter-spacing: 1px;
  opacity: 0.72;
}

.member-tags-more-text {
  font-variant-numeric: tabular-nums;
}

.member-tags-count {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--muted);
}

.member-tags-all {
  max-height: min(52vh, 420px);
  overflow: auto;
  padding-right: 4px;
}
</style>
