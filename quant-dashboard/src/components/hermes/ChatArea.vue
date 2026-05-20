<template>
  <div class="chat-area">
    <!-- Header -->
    <div class="chat-header">
      <span class="header-title">{{ store.currentSession?.title || 'AI 天团' }}</span>
      <button class="btn-clear" @click="store.clearMessages()" v-if="store.messages.length">清空</button>
    </div>

    <!-- Messages -->
    <div class="message-list" ref="listRef">
      <div v-if="store.citations.length" class="citations-bar">
        <div class="citations-label">📎 参考文档 ({{ store.citations.length }})</div>
        <div v-for="c in store.citations.slice(0, 5)" :key="c.source" class="citation-chip">
          {{ c.file_name }}
        </div>
      </div>

      <div v-for="(msg, i) in store.messages" :key="i">
        <MessageBubble :message="msg" :skill="getSkill(msg.skill)" />
      </div>

      <!-- Error state -->
      <div v-if="store.status === 'error' && store.errorMessage" class="error-banner">
        ⚠️ {{ store.errorMessage }}
        <button @click="retryLast()" class="btn-retry">重试</button>
      </div>

      <div ref="bottomRef"></div>
    </div>

    <!-- Input -->
    <ChatInput />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useHermesStore } from '../../stores/hermes'
import type { ChatMessage } from '../../types/hermes'
import MessageBubble from './MessageBubble.vue'
import ChatInput from './ChatInput.vue'

const store = useHermesStore()
const listRef = ref<HTMLElement | null>(null)
const bottomRef = ref<HTMLElement | null>(null)

function getSkill(name?: string) {
  if (!name) return null
  return store.skills.find(s => s.name === name) || null
}

function retryLast() {
  const lastUser = [...store.messages].reverse().find(m => m.role === 'user')
  if (lastUser) {
    store.messages.pop() // remove failed assistant msg
    store.sendMessage(lastUser.content)
  }
}

watch(() => store.messages.length, () => {
  nextTick(() => bottomRef.value?.scrollIntoView({ behavior: 'smooth' }))
})
watch(() => store.streamBuffer.value, () => {
  nextTick(() => bottomRef.value?.scrollIntoView({ behavior: 'smooth' }))
})
</script>

<style scoped>
.chat-area {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #1e293b;
  background: #0b1120;
}
.header-title { font-size: 15px; font-weight: 600; }
.btn-clear {
  background: none;
  border: 1px solid #334155;
  color: #94a3b8;
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.btn-clear:hover { background: #1e293b; }

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.citations-bar {
  margin-bottom: 12px;
  padding: 10px;
  background: #0a1628;
  border: 1px solid #1e3a5f;
  border-radius: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.citations-label { font-size: 12px; color: #6366f1; width: 100%; margin-bottom: 4px; }
.citation-chip {
  font-size: 11px;
  padding: 2px 8px;
  background: #1e293b;
  border-radius: 4px;
  color: #94a3b8;
}

.error-banner {
  margin-top: 8px;
  padding: 10px 14px;
  background: #450a0a;
  border: 1px solid #7f1d1d;
  border-radius: 8px;
  color: #fca5a5;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.btn-retry {
  background: #7f1d1d;
  color: #fca5a5;
  border: none;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
</style>
