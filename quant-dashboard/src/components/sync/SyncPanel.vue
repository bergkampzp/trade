<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useSyncStore } from '@/stores/sync'

const store = useSyncStore()

const syncCards = computed(() => [
  {
    id: 'news' as const,
    icon: '📰',
    title: '新闻数据',
    desc: 'RSS 源: CoinDesk · CoinTelegraph · Decrypt',
    status: store.sources.find(s => s.id === 'news'),
    btnLabel: '⟳ 同步今日新闻',
  },
  {
    id: 'macro' as const,
    icon: '📈',
    title: '宏观经济',
    desc: '数据源: FRED API · yfinance (备用)',
    status: store.sources.find(s => s.id === 'macro'),
    btnLabel: '⟳ 同步今日指标',
  },
  {
    id: 'crypto' as const,
    icon: '₿',
    title: '数字货币行情',
    desc: '数据源: Binance (通过 Freqtrade)',
    status: store.sources.find(s => s.id === 'crypto'),
    btnLabel: '⟳ 同步最新行情',
  },
  {
    id: 'dbt' as const,
    icon: '⚙',
    title: '因子模型 (dbt)',
    desc: '运行 33 个 dbt 模型，更新因子信号',
    status: null,
    btnLabel: '▶ 运行因子模型',
  },
])

function statusClass(v: string | null) {
  if (v === 'running') return 'status-running'
  if (v === 'success') return 'status-success'
  if (v === 'failed') return 'status-failed'
  return ''
}

function statusDot(v: string | null) {
  if (v === 'running') return '🟡'
  if (v === 'success') return '🟢'
  if (v === 'failed') return '🔴'
  return '⚪'
}

function fmtDate(d: string | null) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN', { hour12: false }).slice(0, 16)
}

async function doSync(id: string) {
  await store.sync(id)
}

onMounted(() => store.load())
</script>

<template>
  <div class="sync-panel">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-gray-300">⚡ 数据同步</h3>
      <span class="text-xs text-gray-500">状态: {{ store.running ? '同步中...' : '空闲' }}</span>
    </div>

    <div class="sync-grid">
      <div v-for="card in syncCards" :key="card.id" class="sync-card">
        <div class="flex items-start gap-3">
          <span class="text-xl">{{ card.icon }}</span>
          <div class="flex-1 min-w-0">
            <div class="font-medium text-sm text-gray-200">{{ card.title }}</div>
            <div class="text-xs text-gray-500 mt-0.5">{{ card.desc }}</div>

            <div v-if="card.status" class="mt-2 text-xs">
              <span class="text-gray-500">上次: </span>
              <span :class="statusClass(card.status.last_result)">
                {{ statusDot(card.status.last_result) }} {{ fmtDate(card.status.last_sync) }}
              </span>
              <span class="ml-2 text-gray-600">{{ card.status.row_count }} 条</span>
            </div>
            <div v-else class="mt-2 text-xs text-gray-600">点击按钮运行</div>
          </div>
        </div>

        <button
          class="sync-btn"
          :class="{ running: store.running === card.id }"
          :disabled="store.running !== null"
          @click="doSync(card.id)"
        >
          {{ store.running === card.id ? '同步中...' : card.btnLabel }}
        </button>
      </div>
    </div>

    <!-- 执行日志 -->
    <div class="mt-6">
      <div class="flex items-center justify-between mb-2">
        <h4 class="text-xs font-semibold text-gray-400 uppercase">执行日志</h4>
        <button class="text-xs text-amber-400 hover:text-amber-300" @click="store.load()">⟳ 刷新</button>
      </div>
      <div class="log-list">
        <div v-for="log in store.logs.slice(0, 10)" :key="log.id" class="log-item">
          <span class="text-xs w-6" :class="log.status === 'success' ? 'text-green-400' : 'text-red-400'">
            {{ log.status === 'success' ? '✓' : '✗' }}
          </span>
          <span class="text-xs text-gray-400 w-20 shrink-0">{{ log.source }}</span>
          <span class="text-xs text-gray-300 flex-1 truncate">{{ log.message }}</span>
          <span class="text-xs text-gray-600 w-24 text-right">{{ log.started_at.slice(0, 16).replace('T', ' ') }}</span>
        </div>
        <div v-if="!store.logs.length" class="text-center text-gray-600 py-4 text-xs">暂无日志</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sync-panel {
  padding: 16px;
  overflow-y: auto;
  height: 100%;
}
.sync-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.sync-card {
  background: #1a1a2e;
  border: 1px solid #2a2a3e;
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color 0.2s;
}
.sync-card:hover {
  border-color: #3a3a5e;
}
.sync-btn {
  width: 100%;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid #3a3a5e;
  background: #12121f;
  color: #d1d5db;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
}
.sync-btn:hover:not(:disabled) {
  background: #1f1f35;
  border-color: #f59e0b;
  color: #f59e0b;
}
.sync-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.sync-btn.running {
  border-color: #f59e0b;
  color: #f59e0b;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.status-running { color: #f59e0b; }
.status-success { color: #22c55e; }
.status-failed { color: #ef4444; }
.log-list {
  background: #12121f;
  border-radius: 8px;
  padding: 8px;
  max-height: 240px;
  overflow-y: auto;
}
.log-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 4px;
}
.log-item:hover {
  background: #1a1a2e;
}
</style>
