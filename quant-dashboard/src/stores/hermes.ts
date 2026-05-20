// stores/hermes.ts — AI天团 WebChat Pinia Store

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, ChatStatus, Citation, SessionSummary, SkillInfo } from '../types/hermes'
import * as api from '../api/hermes'

export const useHermesStore = defineStore('hermes', () => {
  // ── State ──
  const skills = ref<SkillInfo[]>([])
  const sessions = ref<SessionSummary[]>([])
  const currentSessionId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const status = ref<ChatStatus>('empty')
  const selectedSkill = ref<string | null>(null)
  const citations = ref<Citation[]>([])
  const errorMessage = ref('')
  const streamBuffer = ref('')

  // ── Getters ──
  const currentSkill = computed(() =>
    skills.value.find(s => s.name === selectedSkill.value) || null
  )
  const currentSession = computed(() =>
    sessions.value.find(s => s.id === currentSessionId.value) || null
  )

  // ── Actions ──
  async function loadSkills() {
    try {
      skills.value = await api.fetchSkills()
    } catch (e) {
      console.error('loadSkills:', e)
    }
  }

  async function loadSessions() {
    try {
      sessions.value = await api.fetchSessions()
    } catch (e) {
      console.error('loadSessions:', e)
    }
  }

  async function newSession(skill?: string) {
    try {
      const res = await api.createSession('新对话', skill)
      currentSessionId.value = res.session_id
      messages.value = []
      citations.value = []
      status.value = 'empty'
      selectedSkill.value = skill || null
      await loadSessions()
    } catch (e) {
      console.error('newSession:', e)
    }
  }

  async function openSession(sid: string) {
    try {
      const detail = await api.loadSession(sid)
      currentSessionId.value = sid
      selectedSkill.value = detail.skill || null
      messages.value = detail.messages || []
      citations.value = []
      status.value = messages.value.length > 0 ? 'ready' : 'empty'
    } catch (e) {
      console.error('openSession:', e)
    }
  }

  async function removeSession(sid: string) {
    try {
      await api.deleteSession(sid)
      if (currentSessionId.value === sid) {
        currentSessionId.value = null
        messages.value = []
        status.value = 'empty'
      }
      await loadSessions()
    } catch (e) {
      console.error('removeSession:', e)
    }
  }

  function sendMessage(text: string) {
    if (!text.trim()) return
    if (status.value === 'streaming') return

    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      skill: selectedSkill.value || undefined,
      timestamp: new Date().toISOString(),
    }
    messages.value.push(userMsg)
    status.value = 'streaming'
    errorMessage.value = ''
    streamBuffer.value = ''
    citations.value = []

    // Add placeholder for assistant response
    const aiMsg: ChatMessage = {
      role: 'assistant',
      content: '',
      skill: selectedSkill.value || undefined,
      timestamp: new Date().toISOString(),
    }
    messages.value.push(aiMsg)
    const aiIndex = messages.value.length - 1

    const abort = api.streamChat(
      {
        message: text,
        skill: selectedSkill.value || undefined,
        session_id: currentSessionId.value || undefined,
      },
      (evt) => {
        if (evt.type === 'text') {
          streamBuffer.value += evt.content
          messages.value[aiIndex].content = streamBuffer.value
        } else if (evt.type === 'citation') {
          citations.value.push({
            source: evt.source,
            file_name: evt.file_name,
            text: evt.text,
            score: evt.score,
          })
        } else if (evt.type === 'error') {
          errorMessage.value = evt.message
          messages.value[aiIndex].content = '❌ ' + evt.message
          status.value = 'error'
        } else if (evt.type === 'done') {
          status.value = 'ready'
          // Save to session
          if (currentSessionId.value) {
            api.appendMessage(currentSessionId.value, userMsg).catch(() => {})
            api.appendMessage(currentSessionId.value, {
              role: 'assistant',
              content: streamBuffer.value,
              skill: selectedSkill.value || undefined,
            }).catch(() => {})
          }
        }
      },
      (err) => {
        errorMessage.value = err
        messages.value[aiIndex].content = '❌ 连接失败: ' + err
        status.value = 'error'
      },
      () => {
        if (status.value === 'streaming') status.value = 'ready'
      },
    )

    return abort
  }

  function selectSkill(name: string | null) {
    selectedSkill.value = name
  }

  function clearMessages() {
    messages.value = []
    citations.value = []
    streamBuffer.value = ''
    status.value = 'empty'
  }

  return {
    skills, sessions, currentSessionId, messages, status,
    selectedSkill, citations, errorMessage, streamBuffer,
    currentSkill, currentSession,
    loadSkills, loadSessions, newSession, openSession, removeSession,
    sendMessage, selectSkill, clearMessages,
  }
})
