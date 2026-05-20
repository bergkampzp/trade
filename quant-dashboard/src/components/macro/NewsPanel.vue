<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useMacroStore } from '@/stores/macro'

const store = useMacroStore()
const expandedId = ref<number | null>(null)
const scrollContainer = ref<HTMLElement | null>(null)
let scrollTimer: ReturnType<typeof setInterval> | null = null
let pauseTimer: ReturnType<typeof setTimeout> | null = null
const isPaused = ref(false)

const topNews = computed(() => store.newsItems.slice(0, 10))

const sentimentList = [
  { key: 'positive', label: '看多', color: 'text-green-400', dot: 'bg-green-400' },
  { key: 'negative', label: '看空', color: 'text-red-400', dot: 'bg-red-400' },
  { key: 'neutral', label: '中性', color: 'text-yellow-400', dot: 'bg-yellow-400' },
]

function sentimentBg(s: string) {
  if (s === 'positive') return 'bg-green-400/10 border-green-400/30'
  if (s === 'negative') return 'bg-red-400/10 border-red-400/30'
  return 'bg-yellow-400/10 border-yellow-400/30'
}

function sentimentIcon(s: string) {
  if (s === 'positive') return '↑'
  if (s === 'negative') return '↓'
  return '→'
}

function sentimentLabel(s: string) {
  for (const item of sentimentList) {
    if (item.key === s) return item.label
  }
  return s
}

function fmtDate(d: string) {
  return d.slice(0, 16).replace('T', ' ')
}

function toggleExpand(idx: number) {
  expandedId.value = expandedId.value === idx ? null : idx
  if (pauseTimer) clearTimeout(pauseTimer)
  isPaused.value = true
  pauseTimer = setTimeout(() => { isPaused.value = false }, 5000)
}

function startAutoScroll() {
  scrollTimer = setInterval(() => {
    if (!scrollContainer.value || isPaused.value || expandedId.value !== null) return
    const el = scrollContainer.value
    const maxScroll = el.scrollHeight - el.clientHeight
    if (el.scrollTop >= maxScroll - 10) {
      el.scrollTo({ top: 0, behavior: 'smooth' })
    } else {
      el.scrollBy({ top: 1, behavior: 'smooth' })
    }
  }, 80)
}

onMounted(async () => {
  await store.loadNews()
  startAutoScroll()
})

onUnmounted(() => {
  if (scrollTimer) clearInterval(scrollTimer)
  if (pauseTimer) clearTimeout(pauseTimer)
})
</script>

<template>
  <div class="news-panel">
    <!-- 顶部栏 -->
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-gray-300">经济新闻</h3>
        <span class="text-xs text-gray-600">| {{ topNews.length }} 条</span>
      </div>
      <div class="flex items-center gap-3">
        <div class="flex gap-2 text-xs">
          <span v-if="store.newsSummary.positive" class="flex items-center gap-1 px-2 py-0.5 rounded bg-green-400/10 text-green-400">
            <span class="w-2 h-2 rounded-full bg-green-400" /> 看多 {{ store.newsSummary.positive }}
          </span>
          <span v-if="store.newsSummary.negative" class="flex items-center gap-1 px-2 py-0.5 rounded bg-red-400/10 text-red-400">
            <span class="w-2 h-2 rounded-full bg-red-400" /> 看空 {{ store.newsSummary.negative }}
          </span>
          <span v-if="store.newsSummary.neutral" class="flex items-center gap-1 px-2 py-0.5 rounded bg-yellow-400/10 text-yellow-400">
            <span class="w-2 h-2 rounded-full bg-yellow-400" /> 中性 {{ store.newsSummary.neutral }}
          </span>
        </div>
        <span class="text-xs text-gray-500">{{ isPaused ? '⏸ 已暂停' : '↻ 自动滚动' }}</span>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!topNews.length && !store.loading" class="text-center text-gray-600 py-16">
      <p class="text-lg mb-2">📰</p>
      <p>暂无新闻数据</p>
      <p class="text-xs mt-2">点击顶部 <code class="text-amber-400 bg-amber-400/10 px-1 rounded">⟳ 同步</code> 按钮获取今日新闻</p>
    </div>

    <!-- 新闻卡片列表 -->
    <div ref="scrollContainer" class="news-scroll" @mouseenter="isPaused = true" @mouseleave="isPaused = false">
      <div
        v-for="(item, idx) in topNews"
        :key="idx"
        class="news-card"
        :class="[sentimentBg(item.sentiment), { expanded: expandedId === idx }]"
        @click="toggleExpand(idx)"
      >
        <!-- 卡片头部（始终可见） -->
        <div class="card-header">
          <div class="flex items-start gap-3">
            <div class="sentiment-dot" :class="sentimentIcon(item.sentiment) === '↑' ? 'text-green-400' : sentimentIcon(item.sentiment) === '↓' ? 'text-red-400' : 'text-yellow-400'">
              <span class="text-lg">{{ sentimentIcon(item.sentiment) }}</span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-gray-200 leading-snug">{{ item.headline }}</div>
              <div class="flex items-center gap-2 mt-1.5">
                <span class="text-xs text-gray-500">{{ item.source }}</span>
                <span class="text-xs text-gray-600">·</span>
                <span class="text-xs text-gray-600">{{ fmtDate(item.published_at) }}</span>
                <span
                  class="sentiment-chip text-xs ml-auto"
                  :class="sentimentBg(item.sentiment)"
                >
                  {{ sentimentLabel(item.sentiment) }}
                  <span class="ml-1" :class="sentimentIcon(item.sentiment) === '↑' ? 'text-green-400' : sentimentIcon(item.sentiment) === '↓' ? 'text-red-400' : 'text-yellow-400'">
                    {{ (item.score * 100).toFixed(0) }}%
                  </span>
                </span>
              </div>
            </div>
            <div class="expand-icon text-gray-600 text-xs mt-1" :class="{ rotated: expandedId === idx }">▼</div>
          </div>
        </div>

        <!-- 展开详情 -->
        <div v-if="expandedId === idx" class="card-detail">
          <div class="divider" />
          <p class="text-sm text-gray-300 leading-relaxed mb-3">{{ item.summary }}</p>
          <div class="detail-grid">
            <div class="detail-item">
              <span class="detail-label">情感倾向</span>
              <span class="detail-value" :class="sentimentIcon(item.sentiment) === '↑' ? 'text-green-400' : sentimentIcon(item.sentiment) === '↓' ? 'text-red-400' : 'text-yellow-400'">
                {{ item.sentiment.toUpperCase() }}
              </span>
            </div>
            <div class="detail-item">
              <span class="detail-label">置信度</span>
              <span class="detail-value text-gray-300">{{ (item.score * 100).toFixed(0) }}%</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">来源</span>
              <span class="detail-value text-gray-400">{{ item.source }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">发布时间</span>
              <span class="detail-value text-gray-400">{{ fmtDate(item.published_at) }}</span>
            </div>
          </div>
          <div class="mt-3 pt-3 border-t border-gray-700/30">
            <div class="relative">
              <div class="score-bar">
                <div class="score-fill" :style="{
                  width: (item.score * 100) + '%',
                  background: item.sentiment === 'positive'
                    ? 'linear-gradient(90deg, #166534, #22c55e)'
                    : item.sentiment === 'negative'
                    ? 'linear-gradient(90deg, #991b1b, #ef4444)'
                    : 'linear-gradient(90deg, #854d0e, #f59e0b)'
                }" />
              </div>
              <div class="flex justify-between text-xs text-gray-500 mt-1">
                <span>看空 0%</span>
                <span>50%</span>
                <span>100% 看多</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.news-panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.news-scroll {
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.news-scroll::-webkit-scrollbar {
  width: 3px;
}
.news-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.news-scroll::-webkit-scrollbar-thumb {
  background: #2a2a3e;
  border-radius: 3px;
}

.news-card {
  border: 1px solid;
  border-radius: 10px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.news-card:hover {
  filter: brightness(1.1);
}
.news-card.expanded {
  border-color: #3a3a5e !important;
}

.card-header {
  display: flex;
}

.sentiment-dot {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: rgba(255,255,255,0.05);
}

.expand-icon {
  transition: transform 0.2s ease;
  flex-shrink: 0;
}
.expand-icon.rotated {
  transform: rotate(180deg);
}

.sentiment-chip {
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid;
  font-weight: 500;
}

.card-detail {
  overflow: hidden;
  animation: slideDown 0.25s ease;
}

@keyframes slideDown {
  from { opacity: 0; max-height: 0; }
  to { opacity: 1; max-height: 200px; }
}

.divider {
  height: 1px;
  background: rgba(255,255,255,0.06);
  margin: 12px 0;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.detail-label {
  font-size: 0.65rem;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.detail-value {
  font-size: 0.8rem;
  font-weight: 500;
}

.score-bar {
  height: 4px;
  background: rgba(255,255,255,0.06);
  border-radius: 2px;
  overflow: hidden;
}

.score-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}
</style>
