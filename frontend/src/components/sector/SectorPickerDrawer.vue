<script setup lang="ts">
import { useDebounceFn, useWindowSize } from '@vueuse/core'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NScrollbar,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useBoardStore } from '@/stores/boardStore'
import type { BoardCatalogType, BoardItem } from '@/types/board'
import { sectorTypeShort } from '@/utils/format'
import {
  BOARD_TAB_TONE,
  sectorTypeClass,
} from '@/utils/sectorTypeStyles'

const boardStore = useBoardStore()
const {
  pickerOpen,
  pickerType,
  pickerQuery,
  pickerCatalog,
  pickerSearchHint,
  pickerSelected,
  pickerSaving,
} = storeToRefs(boardStore)

const typeTabs: { label: string; value: BoardCatalogType }[] = [
  { label: '行业', value: 'HY' },
  { label: '概念', value: 'GN' },
  { label: '二级行业', value: 'HY2' },
  { label: '板块指数', value: 'IDX' },
]

const { width: windowWidth } = useWindowSize()
const drawerWidth = computed(() => Math.round(windowWidth.value * 0.5))
const selectedExpanded = ref(false)

const showSelectedToggle = computed(
  () => pickerSelected.value.length > 6 || selectedExpanded.value,
)

const debouncedSearch = useDebounceFn(() => {
  boardStore.loadCatalog()
}, 250)

watch(pickerType, () => {
  boardStore.loadCatalog()
})

watch(pickerQuery, () => {
  debouncedSearch()
})

watch(pickerOpen, (open) => {
  if (!open) selectedExpanded.value = false
})

function setType(value: BoardCatalogType) {
  pickerType.value = value
}

function typeLabel(item: BoardItem) {
  return sectorTypeShort(item.sector_type, item.id)
}

function toneClass(item: BoardItem) {
  return sectorTypeClass(item.sector_type, item.id)
}

function tabToneClass(tab: BoardCatalogType) {
  return `sector-tone-${BOARD_TAB_TONE[tab] ?? 'default'}`
}
</script>

<template>
  <NDrawer
    :show="pickerOpen"
    :width="drawerWidth"
    placement="right"
    :trap-focus="false"
    display-directive="show"
    @update:show="(v) => !v && boardStore.closePicker()"
  >
    <NDrawerContent :bordered="false" closable class="picker-drawer">
      <template #header>
        <div class="drawer-head">
          <div>
            <div class="drawer-title">自选板块</div>
            <div class="drawer-sub">勾选后保存，首页「自选」模式将展示这些板块</div>
          </div>
        </div>
      </template>

      <div class="picker-body">
        <div class="toolbar-row">
          <div class="type-tabs">
            <button
              v-for="tab in typeTabs"
              :key="tab.value"
              type="button"
              class="type-tab"
              :class="[tabToneClass(tab.value), { active: pickerType === tab.value }]"
              @click="setType(tab.value)"
            >
              <span class="type-tab-dot" aria-hidden="true" />
              {{ tab.label }}
            </button>
          </div>

          <NInput
            v-model:value="pickerQuery"
            clearable
            size="medium"
            placeholder="搜索名称或代码"
            class="search-input"
          />
        </div>

        <div class="selected-card">
          <div class="selected-bar">
            <div class="selected-head">
              <div class="selected-title-row">
                <span class="selected-label">已选 {{ pickerSelected.length }}</span>
                <button
                  v-if="showSelectedToggle"
                  type="button"
                  class="expand-btn"
                  @click="selectedExpanded = !selectedExpanded"
                >
                  {{ selectedExpanded ? '收起' : `查看更多 (${pickerSelected.length})` }}
                </button>
              </div>
            </div>
            <button
              v-if="pickerSelected.length"
              type="button"
              class="link-btn"
              @click="pickerSelected.splice(0)"
            >
              清空勾选
            </button>
          </div>

          <div v-if="pickerSelected.length" class="selected-chips">
            <div class="chip-wrap" :class="{ collapsed: !selectedExpanded }">
              <div
                v-for="b in pickerSelected"
                :key="b.id"
                class="sector-chip"
                :class="toneClass(b)"
              >
                <span class="sector-chip-name" :title="b.name">{{ b.name }}</span>
                <span class="sector-type-badge">{{ typeLabel(b) }}</span>
                <button
                  type="button"
                  class="sector-chip-close"
                  aria-label="移除"
                  @click="boardStore.togglePick(b)"
                >
                  ×
                </button>
              </div>
            </div>
          </div>
          <div v-else class="selected-empty">尚未勾选，从下方点选添加</div>
        </div>

        <div class="grid-wrap">
          <NScrollbar v-if="pickerCatalog.length" class="grid-scroll">
            <div class="sector-grid">
              <button
                v-for="item in pickerCatalog"
                :key="item.id"
                type="button"
                class="sector-tile"
                :class="[toneClass(item), { picked: boardStore.isPicked(item.id) }]"
                @click="boardStore.togglePick(item)"
              >
                <span class="tile-check" aria-hidden="true">
                  <svg
                    v-if="boardStore.isPicked(item.id)"
                    viewBox="0 0 16 16"
                    width="12"
                    height="12"
                    fill="none"
                  >
                    <path
                      d="M3.5 8.2l2.8 2.8 6.2-6.4"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                </span>
                <span class="tile-name">{{ item.name }}</span>
                <span class="tile-meta">
                  <span class="sector-type-badge tile-type-badge">{{ typeLabel(item) }}</span>
                  <span class="tile-code num">{{ item.id }}</span>
                </span>
              </button>
            </div>
          </NScrollbar>
          <NEmpty v-else class="py-12" :description="pickerSearchHint || '无匹配板块'" size="small" />
        </div>
      </div>

      <template #footer>
        <div class="drawer-foot">
          <NButton quaternary size="medium" @click="boardStore.clearPicker">
            清空并回主力榜
          </NButton>
          <NButton
            type="primary"
            size="medium"
            :loading="pickerSaving"
            :disabled="!pickerSelected.length"
            @click="boardStore.savePicker"
          >
            保存自选 ({{ pickerSelected.length }})
          </NButton>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.picker-drawer :deep(.n-drawer-header) {
  padding: 20px 24px 14px;
  border-bottom: 1px solid var(--border);
}

.picker-drawer :deep(.n-drawer-body-content-wrapper) {
  padding: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.picker-drawer :deep(.n-drawer-footer) {
  padding: 14px 20px 18px;
  border-top: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 92%, var(--bg));
}

.drawer-head {
  padding-right: 8px;
}

.drawer-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text);
}

.drawer-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.45;
}

.picker-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
  min-height: 0;
  padding: 16px 20px 10px;
}

.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.type-tabs {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  padding: 4px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--muted) 8%, transparent);
}

.type-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 34px;
  padding: 0 4px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.type-tab-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--sector-tone);
  opacity: 0.72;
  flex-shrink: 0;
}

.type-tab:hover {
  color: var(--text);
  background: color-mix(in srgb, var(--sector-tone-soft) 70%, transparent);
}

.type-tab.active {
  background: var(--sector-tone-soft);
  border-color: var(--sector-tone-border);
  color: var(--sector-tone);
  font-weight: 700;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

.type-tab.active .type-tab-dot {
  opacity: 1;
}

.search-input {
  flex: 0 1 260px;
  width: 260px;
  max-width: 38%;
  min-width: 160px;
}

.search-input :deep(.n-input__input-el) {
  font-size: 13px;
}

.selected-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  background: color-mix(in srgb, var(--muted) 4%, var(--panel));
  padding: 12px 14px;
}

.selected-bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.selected-head {
  min-width: 0;
}

.selected-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.selected-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}

.link-btn {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
  padding-top: 2px;
}

.link-btn:hover {
  color: var(--accent);
}

.selected-chips {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chip-wrap {
  display: flex;
  flex-wrap: wrap;
  align-content: flex-start;
  gap: 8px;
  --chip-row-h: 30px;
  --chip-gap: 8px;
}

.chip-wrap.collapsed {
  max-height: calc(var(--chip-row-h) * 2 + var(--chip-gap));
  overflow: hidden;
}

.expand-btn {
  border: none;
  background: transparent;
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
}

.expand-btn:hover {
  text-decoration: underline;
}

.selected-empty {
  font-size: 12px;
  color: var(--muted);
  padding: 2px 0 4px;
}

.grid-wrap {
  flex: 1;
  min-height: 280px;
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  background: var(--panel);
}

.grid-scroll {
  height: 100%;
  max-height: calc(100vh - 320px);
}

.sector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 10px;
  padding: 14px;
}

.sector-tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-height: 64px;
  padding: 9px 10px 9px 36px;
  border: 1px solid var(--sector-tone-border);
  border-radius: 11px;
  background: color-mix(in srgb, var(--sector-tone-soft) 55%, var(--panel));
  text-align: left;
  cursor: pointer;
  position: relative;
  transition:
    border-color 0.12s ease,
    background-color 0.12s ease,
    box-shadow 0.12s ease,
    transform 0.12s ease;
}

.sector-tile:hover {
  border-color: color-mix(in srgb, var(--sector-tone) 45%, var(--border));
  background: var(--sector-tone-soft);
  transform: translateY(-1px);
}

.sector-tile.picked {
  border-color: var(--sector-tone);
  background: var(--sector-tone-soft);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--sector-tone) 22%, transparent),
    0 2px 8px color-mix(in srgb, var(--sector-tone) 12%, transparent);
}

.tile-check {
  position: absolute;
  left: 10px;
  top: 10px;
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  border: 1.5px solid var(--sector-tone-border);
  color: transparent;
  background: var(--panel);
  transition: all 0.12s ease;
}

.sector-tile.picked .tile-check {
  border-color: var(--sector-tone);
  background: var(--sector-tone);
  color: #fff;
}

.tile-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.25;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tile-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
}

.tile-type-badge {
  font-size: 9px;
  padding: 1px 4px;
}

.tile-code {
  font-size: 10px;
  color: var(--muted);
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-foot {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
