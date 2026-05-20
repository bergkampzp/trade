<script setup lang="ts">
import { ref, nextTick, watch, onMounted, computed } from 'vue'
import { sendChatMessage, fetchSkills } from '@/api/ai'
import type { ChatMessage, ToolCall, SkillInfo } from '@/api/ai'

const props = defineProps<{ pair?: string }>()

const messages = ref<(ChatMessage & { toolCalls?: ToolCall[] })[]>([])
const input = ref('')
const loading = ref(false)
const chatContainer = ref<HTMLDivElement>()
const skills = ref<SkillInfo[]>([])
const selectedSkill = ref('')

// 角色元数据：icon、标签、推荐问题
const roleMetaMap: Record<string, { icon: string; label: string; suggestions: string[]; color: string }> = {
  'financial-analyst': {
    icon: '💰',
    label: '财务分析师',
    color: '#22c55e',
    suggestions: [
      '分析平安银行(000001)的盈利能力和偿债风险',
      '贵州茅台(600519)的现金流质量如何？',
      '宁德时代(300750)近期的成长性评估',
    ],
  },
  'valuation-analyst': {
    icon: '💎',
    label: '估值分析师',
    color: '#a78bfa',
    suggestions: [
      '贵州茅台(600519)当前估值合理吗？用PE和DCF分析',
      '宁德时代(300750)的合理估值区间是多少？',
      '平安银行(000001)被低估还是高估？',
    ],
  },
  'factor-deep-dive': {
    icon: '📊',
    label: '因子分析',
    color: '#f59e0b',
    suggestions: [
      'BTC/USDT 当前的技术面和因子信号如何？',
      '过去7天动量最强的因子是哪些？',
      'BTC/USDT 的综合因子评分是多少？',
    ],
  },
  'macro-briefing': {
    icon: '📈',
    label: '宏观简报',
    color: '#3b82f6',
    suggestions: [
      '今天宏观经济环境对加密货币市场的影响？',
      '最近CPI和利率有什么变化？',
      'VIX波动率指数对市场意味着什么？',
    ],
  },
  'news-impact': {
    icon: '📰',
    label: '新闻分析',
    color: '#ef4444',
    suggestions: [
      '最近有什么影响市场的重要新闻？',
      '当前新闻情感是偏多还是偏空？',
      '最近新闻中哪些主题最受关注？',
    ],
  },
  'cross-asset-comparison': {
    icon: '🔄',
    label: '跨资产对比',
    color: '#8b5cf6',
    suggestions: [
      'BTC/USDT vs ETH/USDT 哪个更强？',
      '综合宏观环境，哪些币对现在最值得关注？',
      '多币对横向对比：动量+波动率排名',
    ],
  },
  'risk-assessment': {
    icon: '⚠️',
    label: '风险评估',
    color: '#f97316',
    suggestions: [
      'BTC/USDT 当前面临的主要风险有哪些？',
      '最大回撤和VaR分析',
      '当前仓位应该做哪些对冲？',
    ],
  },
}

const defaultSuggestions = [
  'BTC/USDT 当前的技术面和因子信号如何？',
  '最近有什么影响市场的重要新闻？',
  '综合宏观环境，哪些币对现在最值得关注？',
]

const currentRoleMeta = computed(() => selectedSkill.value ? roleMetaMap[selectedSkill.value] : null)
const currentSuggestions = computed(() => currentRoleMeta.value?.suggestions || defaultSuggestions)
const currentWelcomeDesc = computed(() => {
  if (!selectedSkill.value) return '我可以分析实时因子信号、宏观经济、新闻情绪和技术面。'
  const s = skills.value.find(x => x.name === selectedSkill.value)
  return s?.description || ''
})

onMounted(async () => {
  try {
    const res = await fetchSkills()
    skills.value = res.skills
  } catch { /* skills not critical */ }
})

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

watch(() => messages.value.length, scrollToBottom)

async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return

  input.value = ''
  messages.value.push({ role: 'user', content: text })
  loading.value = true

  try {
    const recent = messages.value.slice(-11, -1).map(m => ({ role: m.role, content: m.content }))
    recent.push({ role: 'user', content: text })

    const result = await sendChatMessage(recent, props.pair, selectedSkill.value || undefined)
    messages.value.push({
      role: 'assistant',
      content: result.response,
      toolCalls: result.tool_calls?.length ? result.tool_calls : undefined,
    })
  } catch (e: any) {
    messages.value.push({
      role: 'assistant',
      content: '抱歉，分析服务暂时不可用：' + (e.message || e),
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function quickAsk(q: string) {
  input.value = q
  send()
}
</script>

<template>
  <div class="chat-wrapper">
    <!-- 对话区 -->
    <div ref="chatContainer" class="chat-messages">
      <!-- 欢迎提示 -->
      <div v-if="!messages.length" class="welcome">
        <div class="welcome-icon">{{ currentRoleMeta?.icon || '🤖' }}</div>
        <h3>{{ currentRoleMeta ? currentRoleMeta.label + ' · AI 咨询' : 'DeepSeek QuantTrader AI 分析' }}</h3>
        <p class="text-gray-400 text-sm">{{ currentWelcomeDesc }}</p>
        <div v-if="currentRoleMeta" class="role-badge" :style="{ background: currentRoleMeta.color + '22', borderColor: currentRoleMeta.color + '44', color: currentRoleMeta.color }">
          当前角色：{{ currentRoleMeta.label }}
        </div>
        <div class="suggestions" v-if="currentSuggestions.length">
          <button
            v-for="s in currentSuggestions"
            :key="s"
            class="suggestion-btn"
            @click="quickAsk(s)"
          >
            {{ s }}
          </button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-for="(msg, i) in messages" :key="i" class="message-row" :class="msg.role">
        <div class="message-avatar" :class="{ 'role-active': currentRoleMeta && msg.role === 'assistant' }">
          {{ msg.role === 'user' ? '👤' : (currentRoleMeta?.icon || '🤖') }}
        </div>
        <div class="message-bubble">
          <div v-if="currentRoleMeta && msg.role === 'assistant'" class="role-tag" :style="{ color: currentRoleMeta.color }">
            {{ currentRoleMeta.icon }} {{ currentRoleMeta.label }}
          </div>
          <div class="message-text" v-text="msg.content" />

          <!-- 工具调用展示 -->
          <div v-if="msg.toolCalls?.length" class="tool-calls">
            <details v-for="tc in msg.toolCalls" :key="tc.tool">
              <summary class="tool-summary">
                🔧 调用了 <code>{{ tc.tool }}</code>
              </summary>
              <pre class="tool-result">{{ tc.result }}</pre>
            </details>
          </div>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="message-row assistant">
        <div class="message-avatar" :class="{ 'role-active': currentRoleMeta }">{{ currentRoleMeta?.icon || '🤖' }}</div>
        <div class="message-bubble loading">
          <span class="dot-pulse" />
        </div>
      </div>
    </div>

    <!-- 角色选择器 -->
    <div v-if="skills.length" class="skill-bar">
      <span class="skill-label">🎭 角色</span>
      <select v-model="selectedSkill" class="skill-select">
        <option value="">🤖 通用分析</option>
        <option v-for="s in skills" :key="s.name" :value="s.name">
          {{ (roleMetaMap[s.name]?.icon || '🔵') }} {{ roleMetaMap[s.name]?.label || s.name }}
        </option>
      </select>
      <span v-if="selectedSkill && currentRoleMeta" class="skill-hint" :style="{ color: currentRoleMeta.color + 'aa' }">
        {{ currentRoleMeta.label }} — {{ skills.find(s => s.name === selectedSkill)?.description?.split('—')[0]?.trim() || '' }}
      </span>
      <span v-else-if="!selectedSkill" class="skill-hint text-xs text-gray-600">
        选择一个角色以体验专业 AI 分析
      </span>
    </div>

    <!-- 输入区 -->
    <div class="chat-input-area">
      <textarea
        v-model="input"
        class="chat-input"
        placeholder="输入分析问题，Enter 发送..."
        rows="2"
        :disabled="loading"
        @keydown="handleKeydown"
      />
      <button
        class="send-btn"
        :disabled="!input.trim() || loading"
        @click="send"
      >
        {{ loading ? '...' : '发送' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f0f1a;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.welcome {
  text-align: center;
  padding: 40px 20px;
}
.welcome-icon {
  font-size: 3rem;
  margin-bottom: 12px;
}
.welcome h3 {
  color: #f59e0b;
  font-size: 1.2rem;
  margin-bottom: 6px;
}
.role-badge {
  display: inline-block; padding: 4px 14px; border-radius: 20px;
  font-size: 0.72rem; font-weight: 600; margin: 4px 0 10px; border: 1px solid;
}
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 16px;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}
.suggestion-btn {
  padding: 8px 14px;
  font-size: 0.78rem;
  color: #d1d5db;
  background: #1a1a2e;
  border: 1px solid #2a2a3e;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.15s;
}
.suggestion-btn:hover {
  border-color: #f59e0b;
  color: #f59e0b;
}

.message-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: flex-start;
}
.message-row.user {
  flex-direction: row-reverse;
}
.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #1a1a2e;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  flex-shrink: 0;
}
.message-avatar.role-active {
  border: 1px solid #3a3a5e;
  background: #252540;
}
.message-bubble {
  max-width: 75%;
  background: #1a1a2e;
  border: 1px solid #2a2a3e;
  border-radius: 12px;
  padding: 12px 16px;
}
.message-row.user .message-bubble {
  background: #2a2a4a;
  border-color: #3a3a5e;
}
.message-text {
  color: #e5e7eb;
  font-size: 0.85rem;
  line-height: 1.6;
  white-space: pre-wrap;
}
.role-tag {
  font-size: 0.65rem; font-weight: 600; margin-bottom: 4px;
}
.message-bubble.loading {
  padding: 14px 24px;
}

.dot-pulse::after {
  content: '●';
  animation: dotPulse 1.5s infinite;
  color: #f59e0b;
  font-size: 1.2rem;
}
@keyframes dotPulse {
  0%, 100% { opacity: 0.2; }
  50% { opacity: 1; }
}

.tool-calls {
  margin-top: 10px;
  border-top: 1px solid #2a2a3e;
  padding-top: 8px;
}
.tool-summary {
  font-size: 0.75rem;
  color: #6b7280;
  cursor: pointer;
  user-select: none;
}
.tool-summary code {
  color: #22c55e;
  background: #12121f;
  padding: 1px 6px;
  border-radius: 4px;
}
.tool-result {
  font-size: 0.7rem;
  color: #9ca3af;
  background: #12121f;
  padding: 8px;
  border-radius: 6px;
  margin-top: 6px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.skill-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  border-top: 1px solid #2a2a3e;
  background: #0a0a14;
}
.skill-label {
  font-size: 0.7rem; color: #6b7280; font-weight: 600; white-space: nowrap;
}
.skill-select {
  background: #12121f;
  border: 1px solid #2a2a3e;
  border-radius: 6px;
  padding: 6px 10px;
  color: #d1d5db;
  font-size: 0.78rem;
  outline: none;
  cursor: pointer;
  min-width: 180px;
}
.skill-select:focus {
  border-color: #f59e0b;
}
.skill-hint {
  color: #6b7280;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-input-area {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #2a2a3e;
  background: #0a0a14;
}
.chat-input {
  flex: 1;
  background: #12121f;
  border: 1px solid #2a2a3e;
  border-radius: 8px;
  padding: 10px 14px;
  color: #e5e7eb;
  font-size: 0.82rem;
  font-family: inherit;
  resize: none;
  outline: none;
}
.chat-input:focus {
  border-color: #f59e0b;
}
.send-btn {
  padding: 8px 18px;
  background: #f59e0b;
  color: #0f0f1a;
  border: none;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  align-self: flex-end;
}
.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
