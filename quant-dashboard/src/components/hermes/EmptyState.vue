<template>
  <div class="empty-state">
    <div class="hero">
      <div class="hero-icon">🧠</div>
      <h1>AI 天团</h1>
      <p class="hero-sub">选择一位专家，开始你的 AI 咨询</p>
    </div>

    <div class="role-cards">
      <button
        v-for="s in store.skills.slice(0, 5)"
        :key="s.name"
        class="role-card"
        @click="startWithSkill(s.name)"
      >
        <div class="role-icon" :style="{ background: s.color + '22', color: s.color }">
          {{ s.icon }}
        </div>
        <div class="role-label">{{ s.label }}</div>
        <div class="role-desc">{{ s.description }}</div>
      </button>
    </div>

    <div class="suggestions" v-if="store.currentSkill?.suggestions.length">
      <div class="suggestions-title">💡 推荐问题</div>
      <button
        v-for="(q, i) in store.currentSkill.suggestions"
        :key="i"
        class="suggestion-chip"
        @click="quickAsk(q)"
      >{{ q }}</button>
    </div>

    <div class="upload-hint" v-if="!store.selectedSkill">
      <div class="upload-area" @click="triggerUpload" @dragover.prevent @drop.prevent="handleDrop">
        📎 上传文档以获得更精准的分析
        <br><span class="hint-sub">拖拽 PDF / Word 到此处，或点击选择</span>
      </div>
      <input ref="fileInput" type="file" accept=".pdf,.docx,.txt,.md" hidden multiple @change="handleFiles" />
    </div>

    <ChatInput />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useHermesStore } from '../../stores/hermes'
import { uploadFile } from '../../api/hermes'
import ChatInput from './ChatInput.vue'

const store = useHermesStore()
const fileInput = ref<HTMLInputElement | null>(null)

function startWithSkill(name: string) {
  store.selectSkill(name)
  store.newSession(name)
}

function quickAsk(q: string) {
  store.sendMessage(q)
}

function triggerUpload() { fileInput.value?.click() }

function handleFiles(e: Event) {
  const inp = e.target as HTMLInputElement
  if (inp.files) {
    for (const f of inp.files) uploadFile(f).catch(console.warn)
  }
}

function handleDrop(e: DragEvent) {
  if (e.dataTransfer?.files) {
    for (const f of e.dataTransfer.files) uploadFile(f).catch(console.warn)
  }
}
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 40px 20px;
  overflow-y: auto;
}

.hero { text-align: center; margin-bottom: 32px; }
.hero-icon { font-size: 48px; margin-bottom: 8px; }
h1 { font-size: 28px; margin: 0 0 8px; color: #e2e8f0; }
.hero-sub { font-size: 15px; color: #94a3b8; margin: 0; }

.role-cards {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
  margin-bottom: 24px;
  max-width: 700px;
}

.role-card {
  width: 130px;
  padding: 16px 12px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 12px;
  cursor: pointer;
  text-align: center;
  color: #e2e8f0;
  transition: border-color 0.2s;
}
.role-card:hover { border-color: #6366f1; }

.role-icon { font-size: 28px; width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; margin: 0 auto 8px; }
.role-label { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
.role-desc { font-size: 11px; color: #64748b; line-height: 1.4; }

.suggestions {
  max-width: 500px;
  width: 100%;
  margin-bottom: 24px;
}
.suggestions-title { font-size: 13px; color: #94a3b8; margin-bottom: 8px; }
.suggestion-chip {
  display: block;
  width: 100%;
  padding: 10px 14px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #e2e8f0;
  text-align: left;
  cursor: pointer;
  margin-bottom: 6px;
  font-size: 14px;
}
.suggestion-chip:hover { background: #334155; }

.upload-hint {
  max-width: 400px;
  width: 100%;
  margin-bottom: 24px;
}
.upload-area {
  padding: 24px;
  border: 2px dashed #334155;
  border-radius: 12px;
  text-align: center;
  color: #64748b;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.2s;
}
.upload-area:hover { border-color: #6366f1; }
.hint-sub { font-size: 12px; color: #475569; }
</style>
