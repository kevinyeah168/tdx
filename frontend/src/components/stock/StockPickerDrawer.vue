<script setup lang="ts">
import { useDebounceFn } from '@vueuse/core'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NScrollbar,
  NTag,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { computed, watch } from 'vue'
import { useBoardStore } from '@/stores/boardStore'

const boardStore = useBoardStore()
const {
  stockPickerOpen,
  stockPickerQuery,
  stockPickerCatalog,
  stockPickerSelected,
  stockPickerSaving,
} = storeToRefs(boardStore)

const drawerWidth = computed(() => Math.min(760, Math.max(620, Math.round(window.innerWidth * 0.48))))

const debouncedSearch = useDebounceFn(() => {
  boardStore.loadStockCatalog()
}, 250)

watch(stockPickerQuery, () => {
  debouncedSearch()
})
</script>

<template>
  <NDrawer
    :show="stockPickerOpen"
    :width="drawerWidth"
    placement="right"
    :trap-focus="false"
    display-directive="show"
    @update:show="(v) => !v && boardStore.closeStockPicker()"
  >
    <NDrawerContent :bordered="false" closable class="picker-drawer">
      <template #header>
        <div class="drawer-head">
          <div>
            <div class="drawer-title">自选个股</div>
            <div class="drawer-sub">搜索并勾选后保存，首页「自选」模式将展示这些个股</div>
          </div>
        </div>
      </template>

      <div class="picker-body">
        <NInput
          v-model:value="stockPickerQuery"
          clearable
          size="medium"
          placeholder="搜索名称或代码，如 600519、茅台"
          class="search-input"
        />

        <div class="selected-card">
          <div class="selected-bar">
            <span class="selected-label">已选 {{ stockPickerSelected.length }}</span>
            <button
              v-if="stockPickerSelected.length"
              type="button"
              class="link-btn"
              @click="stockPickerSelected.splice(0)"
            >
              清空勾选
            </button>
          </div>
          <NScrollbar v-if="stockPickerSelected.length" style="max-height: 72px">
            <div class="chip-wrap">
              <NTag
                v-for="s in stockPickerSelected"
                :key="s.id"
                closable
                size="small"
                round
                :bordered="false"
                class="chip"
                @close="boardStore.toggleStockPick(s)"
              >
                {{ s.name }}
              </NTag>
            </div>
          </NScrollbar>
          <div v-else class="selected-empty">输入关键词搜索后点选添加</div>
        </div>

        <div class="grid-wrap">
          <NScrollbar v-if="stockPickerCatalog.length" class="grid-scroll">
            <div class="stock-grid">
              <button
                v-for="item in stockPickerCatalog"
                :key="item.id"
                type="button"
                class="stock-tile"
                :class="{ picked: boardStore.isStockPicked(item.id) }"
                @click="boardStore.toggleStockPick(item)"
              >
                <span class="tile-check" aria-hidden="true">
                  <svg
                    v-if="boardStore.isStockPicked(item.id)"
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
                <span class="tile-code num">{{ item.id }}</span>
              </button>
            </div>
          </NScrollbar>
          <NEmpty
            v-else
            class="py-12"
            :description="stockPickerQuery.trim() ? '无匹配个股' : '输入关键词开始搜索'"
            size="small"
          />
        </div>
      </div>

      <template #footer>
        <div class="drawer-foot">
          <NButton quaternary size="medium" @click="boardStore.clearStockPicker">
            清空并回联动
          </NButton>
          <NButton
            type="primary"
            size="medium"
            :loading="stockPickerSaving"
            :disabled="!stockPickerSelected.length"
            @click="boardStore.saveStockPicker"
          >
            保存自选 ({{ stockPickerSelected.length }})
          </NButton>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.picker-drawer :deep(.n-drawer-header) {
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--border);
}

.picker-drawer :deep(.n-drawer-body-content-wrapper) {
  padding: 0;
}

.picker-drawer :deep(.n-drawer-footer) {
  padding: 12px 16px 16px;
  border-top: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 92%, var(--bg));
}

.drawer-head {
  padding-right: 8px;
}

.drawer-title {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text);
}

.drawer-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.4;
}

.picker-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
  padding: 14px 16px 8px;
}

.search-input :deep(.n-input__input-el) {
  font-size: 13px;
}

.selected-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: color-mix(in srgb, var(--accent) 4%, var(--panel));
  padding: 10px 12px;
}

.selected-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.selected-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.link-btn {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
}

.link-btn:hover {
  color: var(--accent);
}

.chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-bottom: 2px;
}

.chip {
  background: color-mix(in srgb, var(--accent) 12%, var(--panel)) !important;
  color: var(--accent) !important;
}

.selected-empty {
  font-size: 12px;
  color: var(--muted);
  padding: 2px 0 4px;
}

.grid-wrap {
  flex: 1;
  min-height: 320px;
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  background: var(--panel);
}

.grid-scroll {
  height: 100%;
  max-height: calc(100vh - 280px);
}

.stock-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
}

@media (min-width: 900px) {
  .stock-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

.stock-tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-height: 58px;
  padding: 8px 10px 8px 34px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
  text-align: left;
  cursor: pointer;
  position: relative;
  transition:
    border-color 0.12s ease,
    background-color 0.12s ease,
    box-shadow 0.12s ease;
}

.stock-tile:hover {
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: color-mix(in srgb, var(--accent) 4%, var(--panel));
}

.stock-tile.picked {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
  background: color-mix(in srgb, var(--accent) 10%, var(--panel));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent);
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
  border: 1.5px solid var(--border);
  color: transparent;
  background: var(--panel);
  transition: all 0.12s ease;
}

.stock-tile.picked .tile-check {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}

.tile-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  line-height: 1.25;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tile-code {
  font-size: 10px;
  color: var(--muted);
  line-height: 1.2;
}

.drawer-foot {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
