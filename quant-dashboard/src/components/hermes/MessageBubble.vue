<template>
  <div :class="['message-bubble', msg.role]">
    <div class="msg-header">
      <span v-if="skill" class="skill-badge" :style="{ background: skill.color }">
        {{ skill.icon }} {{ skill.label }}
      </span>
      <span v-else-if="msg.role === 'user'" class="user-badge">👤 我</span>
      <span class="msg-time">{{ fmtTime(msg.timestamp) }}</span>
    </div>
    <div class="msg-content" v-html="renderMarkdown(msg.content)"></div>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage, SkillInfo } from '../../types/hermes'

const props = defineProps<{
  message: ChatMessage
  skill: SkillInfo | null
}>()

const msg = props.message

function fmtTime(ts?: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  // Simple markdown → HTML (code blocks, bold, lists, line breaks)
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  // Code blocks
  html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // Italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  // Headers
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>')
  // List items
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>')
  // Line breaks
  html = html.replace(/\n\n/g, '<br><br>')
  html = html.replace(/\n/g, '<br>')
  return html
}
</script>

<style scoped>
.message-bubble {
  margin-bottom: 16px;
  max-width: 85%;
}
.message-bubble.user {
  margin-left: auto;
}

.msg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
}

.skill-badge {
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-weight: 600;
  font-size: 12px;
}
.user-badge {
  padding: 2px 8px;
  background: #334155;
  border-radius: 4px;
  color: #e2e8f0;
}
.msg-time {
  color: #64748b;
  margin-left: auto;
}

.msg-content {
  padding: 12px 16px;
  background: #1e293b;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  color: #e2e8f0;
}
.user .msg-content {
  background: #6366f1;
}
.msg-content :deep(pre) {
  background: #0f1729;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
}
.msg-content :deep(code) {
  background: #0f1729;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.msg-content :deep(h3) {
  font-size: 16px;
  margin: 12px 0 6px;
  color: #a5b4fc;
}
.msg-content :deep(h4) {
  font-size: 14px;
  margin: 8px 0 4px;
  color: #c7d2fe;
}
.msg-content :deep(li) {
  margin: 2px 0;
  padding-left: 4px;
}
</style>
