<template>
  <aside class="session-sidebar">
    <div class="sidebar-header">
      <button class="btn-new" @click="store.newSession()">＋ 新对话</button>
    </div>

    <div class="session-list">
      <div v-if="!store.sessions.length" class="empty-hint">暂无历史对话</div>
      <button
        v-for="s in store.sessions"
        :key="s.id"
        :class="['session-item', { active: s.id === store.currentSessionId }]"
        @click="store.openSession(s.id)"
        @dblclick="startRename(s)"
      >
        <span v-if="renaming === s.id" class="session-title">
          <input
            ref="renameInput"
            v-model="renameText"
            class="rename-input"
            @blur="confirmRename"
            @keydown.enter="confirmRename"
            @keydown.escape="renaming = null"
            @click.stop
          />
        </span>
        <span v-else class="session-title">{{ s.title || '新对话' }}</span>
        <span class="session-meta">{{ s.message_count }} 条 · {{ fmtTime(s.updated_at) }}</span>
        <button class="btn-delete" @click.stop="store.removeSession(s.id)" title="删除">×</button>
      </button>
    </div>

    <div class="sidebar-footer">
      <div class="status-row">
        <span class="dot green"></span> {{ store.sessions.length }} 个会话
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useHermesStore } from '../../stores/hermes'
import type { SessionSummary } from '../../types/hermes'

const store = useHermesStore()
const renaming = ref<string | null>(null)
const renameText = ref('')
const renameInput = ref<HTMLInputElement | null>(null)

function startRename(s: SessionSummary) {
  renaming.value = s.id
  renameText.value = s.title || '新对话'
  nextTick(() => {
    const el = document.querySelector('.rename-input') as HTMLInputElement
    el?.focus()
    el?.select()
  })
}

function confirmRename() {
  if (renaming.value && renameText.value.trim()) {
    store.renameCurrent(renameText.value.trim())
  }
  renaming.value = null
}

function fmtTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 3600_000) return Math.floor(diff / 60_000) + '分钟前'
  if (diff < 86400_000) return Math.floor(diff / 3600_000) + '小时前'
  return d.toLocaleDateString('zh-CN')
}
</script>

<style scoped>
.session-sidebar {
  width: 240px;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #1e293b;
  background: #0b1120;
}

.sidebar-header {
  padding: 12px;
  border-bottom: 1px solid #1e293b;
}

.btn-new {
  width: 100%;
  padding: 8px;
  background: #6366f1;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}
.btn-new:hover { background: #5558e6; }

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.empty-hint {
  padding: 24px 12px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}

.session-item {
  display: flex;
  flex-direction: column;
  width: 100%;
  padding: 10px 12px;
  background: transparent;
  border: none;
  color: #e2e8f0;
  text-align: left;
  border-radius: 8px;
  cursor: pointer;
  position: relative;
}
.session-item:hover { background: #1e293b; }
.session-item.active { background: #1e3a5f; }

.session-title {
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}
.btn-delete {
  position: absolute;
  right: 8px;
  top: 8px;
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 16px;
  opacity: 0;
}
.session-item:hover .btn-delete { opacity: 1; }
.btn-delete:hover { color: #ef4444; }

.rename-input {
  width: 100%;
  background: #0f1729;
  border: 1px solid #6366f1;
  border-radius: 4px;
  color: #e2e8f0;
  padding: 2px 6px;
  font-size: 14px;
  outline: none;
}

.sidebar-footer {
  padding: 10px 12px;
  border-top: 1px solid #1e293b;
  font-size: 12px;
  color: #64748b;
}
.status-row { display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.dot.green { background: #22c55e; }
</style>
