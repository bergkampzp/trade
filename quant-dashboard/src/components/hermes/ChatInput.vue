<template>
  <div class="chat-input-wrapper">
    <!-- Attachment preview -->
    <div v-if="files.length" class="attachment-preview">
      <div v-for="(f, i) in files" :key="i" class="file-tag">
        📄 {{ f.name }}
        <button @click="removeFile(i)" class="btn-remove">×</button>
      </div>
    </div>

    <div class="input-row">
      <!-- Agent selector -->
      <div class="agent-select" ref="agentRef">
        <button class="agent-chip" @click="toggleAgentList">
          <span v-if="store.selectedSkill" :style="{ color: store.currentSkill?.color }">
            {{ store.currentSkill?.icon }} {{ store.currentSkill?.label }}
          </span>
          <span v-else>@ 选择角色</span>
          <span class="arrow">▾</span>
        </button>
        <div v-if="showAgentList" class="agent-dropdown">
          <button class="agent-option" @click="selectAgent(null)">
            🤖 通用助手
          </button>
          <button
            v-for="s in store.skills"
            :key="s.name"
            class="agent-option"
            :class="{ selected: s.name === store.selectedSkill }"
            @click="selectAgent(s.name)"
          >
            <span :style="{ color: s.color }">{{ s.icon }}</span>
            <span class="agent-label">{{ s.label }}</span>
            <span class="agent-desc">{{ s.description }}</span>
          </button>
        </div>
      </div>

      <!-- Input -->
      <textarea
        ref="inputRef"
        v-model="inputText"
        class="chat-textarea"
        placeholder="输入消息，或 @ 点名专家..."
        rows="1"
        @keydown.enter.exact.prevent="handleSend"
        @input="autoResize"
        :disabled="store.status === 'streaming'"
      ></textarea>

      <!-- Buttons -->
      <button class="btn-attach" @click="triggerUpload" title="上传文件">📎</button>
      <input ref="fileInputRef" type="file" accept=".pdf,.docx,.txt,.md" hidden @change="handleFileSelect" multiple />

      <button
        v-if="store.status === 'streaming'"
        class="btn-stop"
        @click="handleStop"
        title="停止"
      >■</button>
      <button
        v-else
        class="btn-send"
        @click="handleSend"
        :disabled="!inputText.trim()"
        title="发送"
      >→</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useHermesStore } from '../../stores/hermes'
import { uploadFile } from '../../api/hermes'

const store = useHermesStore()
const inputText = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const agentRef = ref<HTMLElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const files = ref<File[]>([])
const showAgentList = ref(false)
let abortCtrl: AbortController | null = null

function toggleAgentList() {
  showAgentList.value = !showAgentList.value
}

function selectAgent(name: string | null) {
  store.selectSkill(name)
  showAgentList.value = false
}

function handleSend() {
  const text = inputText.value.trim()
  if (!text) return
  inputText.value = ''

  // Upload files first
  if (files.value.length) {
    Promise.all(files.value.map(f => uploadFile(f).catch(e => console.warn('upload fail', e))))
      .finally(() => { files.value = [] })
  }

  abortCtrl = store.sendMessage(text)
  nextTick(() => autoResize())
}

function handleStop() {
  abortCtrl?.abort()
  store.status = 'ready'
}

function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function triggerUpload() {
  fileInputRef.value?.click()
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files) {
    for (const f of input.files) files.value.push(f)
  }
  input.value = ''
}

function removeFile(i: number) {
  files.value.splice(i, 1)
}

// Close agent list on outside click
function onClickOutside(e: MouseEvent) {
  if (agentRef.value && !agentRef.value.contains(e.target as Node)) {
    showAgentList.value = false
  }
}

onMounted(() => document.addEventListener('click', onClickOutside))
onUnmounted(() => document.removeEventListener('click', onClickOutside))
</script>

<style scoped>
.chat-input-wrapper {
  border-top: 1px solid #1e293b;
  background: #0b1120;
}

.attachment-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 16px 0;
}

.file-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  background: #1e293b;
  border-radius: 6px;
  font-size: 12px;
  color: #94a3b8;
}
.btn-remove {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 14px;
}
.btn-remove:hover { color: #ef4444; }

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
}

.agent-select {
  position: relative;
  flex-shrink: 0;
}

.agent-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.agent-chip:hover { background: #334155; }
.arrow { font-size: 10px; color: #64748b; }

.agent-dropdown {
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: 4px;
  width: 240px;
  max-height: 300px;
  overflow-y: auto;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  z-index: 10;
}

.agent-option {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 14px;
  background: transparent;
  border: none;
  color: #e2e8f0;
  text-align: left;
  cursor: pointer;
  font-size: 13px;
}
.agent-option:hover { background: #334155; }
.agent-option.selected { background: #1e3a5f; }

.agent-label { font-weight: 600; flex: 1; }
.agent-desc { width: 100%; font-size: 11px; color: #64748b; }

.chat-textarea {
  flex: 1;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #e2e8f0;
  padding: 8px 12px;
  font-size: 14px;
  resize: none;
  outline: none;
  min-height: 36px;
  max-height: 120px;
  font-family: inherit;
}
.chat-textarea:focus { border-color: #6366f1; }
.chat-textarea:disabled { opacity: 0.5; }

.btn-attach, .btn-send, .btn-stop {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.btn-attach { background: #1e293b; color: #94a3b8; }
.btn-attach:hover { background: #334155; }
.btn-send { background: #6366f1; color: #fff; }
.btn-send:hover { background: #5558e6; }
.btn-send:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-stop { background: #ef4444; color: #fff; }
</style>
