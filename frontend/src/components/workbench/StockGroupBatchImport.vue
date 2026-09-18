<script setup lang="ts">
import { NAlert, NButton, NInput, NModal } from 'naive-ui'
import { computed, ref, watch } from 'vue'

import { addStockGroupMembers, MAX_GROUP_MEMBERS } from '@/api/stockGroups'
import { resolveStockSymbols } from '@/api/stocks'
import { parseStockPasteText } from '@/utils/stockInput'

const props = defineProps<{
  groupId: string
  existingCount: number
}>()

const show = defineModel<boolean>('show', { required: true })

const emit = defineEmits<{
  imported: []
}>()

const pasteText = ref('')
const importing = ref(false)
const error = ref('')
const resultMessage = ref('')

const tokenCount = computed(() => parseStockPasteText(pasteText.value).length)
const remainingSlots = computed(() => Math.max(0, MAX_GROUP_MEMBERS - props.existingCount))

watch(show, (visible) => {
  if (!visible) {
    pasteText.value = ''
    error.value = ''
    resultMessage.value = ''
  }
})

async function importSymbols() {
  const tokens = parseStockPasteText(pasteText.value)
  if (!tokens.length) {
    error.value = '请粘贴代码或名称'
    return
  }
  importing.value = true
  error.value = ''
  resultMessage.value = ''
  try {
    const resolved = await resolveStockSymbols(tokens)
    if (!resolved.resolved.length) {
      error.value = '未能识别任何有效个股，请检查格式（如 SH600000、600000）'
      return
    }
    const symbols = resolved.resolved.map((item) => item.symbol)
    if (symbols.length > remainingSlots.value) {
      error.value = `当前分组最多还可添加 ${remainingSlots.value} 只，请减少导入数量`
      return
    }
    await addStockGroupMembers(props.groupId, symbols)
    const unresolvedNote = resolved.unresolved.length
      ? `；未识别 ${resolved.unresolved.length} 条：${resolved.unresolved.slice(0, 5).join('、')}${resolved.unresolved.length > 5 ? '…' : ''}`
      : ''
    resultMessage.value = `成功导入 ${symbols.length} 只${unresolvedNote}`
    emit('imported')
    if (!resolved.unresolved.length) {
      show.value = false
    }
  } catch (importError) {
    error.value = importError instanceof Error ? importError.message : String(importError)
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <NModal v-model:show="show" preset="card" title="批量导入个股" style="width: 480px">
    <div class="batch-import">
      <p class="hint">
        支持粘贴多行，或用逗号、空格、分号分隔。可识别 SH600000、600000 等格式。
        当前还可添加 <strong>{{ remainingSlots }}</strong> 只。
      </p>
      <NInput
        v-model:value="pasteText"
        type="textarea"
        :autosize="{ minRows: 6, maxRows: 12 }"
        placeholder="SH600000&#10;SZ000001&#10;600519"
      />
      <p v-if="tokenCount" class="hint">已解析 {{ tokenCount }} 条输入</p>
      <NAlert v-if="error" type="error" :show-icon="false">{{ error }}</NAlert>
      <NAlert v-if="resultMessage" type="success" :show-icon="false">{{ resultMessage }}</NAlert>
      <div class="footer-row">
        <NButton quaternary @click="show = false">取消</NButton>
        <NButton type="primary" :loading="importing" @click="importSymbols">导入</NButton>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.batch-import {
  display: grid;
  gap: 10px;
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.footer-row {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
