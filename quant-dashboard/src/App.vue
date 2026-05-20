<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useQuantStore } from '@/stores/quant'
import { useMacroStore } from '@/stores/macro'
import { useSyncStore } from '@/stores/sync'
import { login, restoreToken } from '@/api/client'
import { triggerSync } from '@/api/sync'
import AppLayout from '@/components/layout/AppLayout.vue'
import DataSourcePanel from '@/components/data-source/DataSourcePanel.vue'
import FactorRankingPanel from '@/components/factor/FactorRankingPanel.vue'
import CandlestickChart from '@/components/chart/CandlestickChart.vue'
import FactorDetailPanel from '@/components/chart/FactorDetailPanel.vue'
import MacroDashboard from '@/components/macro/MacroDashboard.vue'
import NewsPanel from '@/components/macro/NewsPanel.vue'
import AnalysisPanel from '@/components/macro/AnalysisPanel.vue'
import SyncPanel from '@/components/sync/SyncPanel.vue'
import AIChat from '@/components/ai/AIChat.vue'
import TradeLab from '@/components/trade/TradeLab.vue'
import DebateLab from '@/components/debate/DebateLab.vue'
import HermesChat from '@/components/hermes/HermesChat.vue'

const store = useQuantStore()
const macroStore = useMacroStore()
const syncStore = useSyncStore()
const authError = ref('')
const ready = ref(false)
const activeTab = ref<'factors' | 'macro' | 'news' | 'analysis' | 'sync' | 'ai' | 'trade' | 'debate' | 'hermes'>('factors')
const syncing = ref<string | null>(null)

const tabs = [
  { id: 'factors' as const, label: '因子研究' },
  { id: 'macro' as const, label: '宏观数据' },
  { id: 'news' as const, label: '经济新闻' },
  { id: 'ai' as const, label: 'AI分析' },
  { id: 'trade' as const, label: '策略实验室' },
  { id: 'analysis' as const, label: '分析结论' },
  { id: 'sync' as const, label: '数据同步' },
  { id: 'debate' as const, label: '辩论分析' },
  { id: 'hermes' as const, label: '🤖 AI天团' },
]

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

// 原始逻辑：切换 Tab 时主动刷新对应数据
function switchTab(tab: typeof activeTab.value) {
  activeTab.value = tab
  if (tab === 'macro' || tab === 'analysis') macroStore.loadIndicators()
  if (tab === 'news') macroStore.loadNews()
  if (tab === 'sync') syncStore.load()
}

const syncLabel = computed(() => {
  if (syncing.value) return '⟳ 同步中...'
  return '⟳ 同步'
})

async function pollUntilDone(source: string) {
  for (let i = 0; i < 30; i++) {
    await sleep(2000)
    try {
      const status = await syncStore.load()
      const items = syncStore.sources
      const src = items.find(s => s.id === source)
      if (src && src.status !== 'running') {
        return src.status === 'success'
      }
    } catch {
      // 继续轮询
    }
  }
  return false
}

async function syncCurrent() {
  const tab = activeTab.value
  if (syncing.value) return
  const source = tab === 'factors' ? 'crypto' : tab === 'news' ? 'news' : 'macro'
  syncing.value = source
  try {
    await triggerSync(source)
    const success = await pollUntilDone(source)
    if (tab === 'news') {
      await macroStore.loadNews()
    } else if (tab === 'macro' || tab === 'analysis') {
      await macroStore.loadIndicators()
    } else if (tab === 'factors') {
      await store.loadDataSources()
      store.refreshCurrentData()
    }
    if (tab === 'sync') await syncStore.load()
  } catch (e: any) {
    console.error('同步失败:', e)
  } finally {
    syncing.value = null
  }
}

onMounted(async () => {
  try {
    if (!restoreToken()) {
      await login('quant', 'quant123')
    }
    await Promise.all([store.loadDataSources(), store.loadFactors()])
    ready.value = true
  } catch (e: any) {
    try {
      await login('quant', 'quant123')
      await Promise.all([store.loadDataSources(), store.loadFactors()])
      ready.value = true
    } catch (e2: any) {
      authError.value = '连接失败: ' + (e2.message || e2)
    }
  }
})
</script>

<template>
  <div v-if="authError" class="h-screen flex items-center justify-center bg-[#0f0f1a] text-red-400 text-sm">
    {{ authError }}
  </div>
  <AppLayout v-else>
    <template #header>
      <div class="flex items-center justify-between w-full">
        <div class="tab-nav">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            class="tab-btn"
            :class="{ active: activeTab === tab.id }"
            @click="switchTab(tab.id)"
          >
            {{ tab.label }}
          </button>
        </div>
        <button
          class="sync-btn"
          :disabled="!!syncing"
          @click="syncCurrent"
        >
          {{ syncLabel }}
        </button>
      </div>
    </template>

    <template #sidebar>
      <template v-if="activeTab === 'factors'">
        <DataSourcePanel />
        <div class="border-t border-gray-800" />
        <FactorRankingPanel />
      </template>
    </template>

    <template #main>
      <template v-if="activeTab === 'factors'">
        <CandlestickChart />
        <div class="border-t border-gray-800" />
        <FactorDetailPanel />
      </template>
      <template v-else-if="activeTab === 'macro'">
        <MacroDashboard />
      </template>
      <template v-else-if="activeTab === 'news'">
        <NewsPanel />
      </template>
      <template v-else-if="activeTab === 'ai'">
        <AIChat :pair="store.selectedPair || 'BTC/USDT'" />
      </template>
      <template v-else-if="activeTab === 'trade'">
        <TradeLab />
      </template>
      <template v-else-if="activeTab === 'analysis'">
        <AnalysisPanel />
      </template>
      <template v-else-if="activeTab === 'sync'">
        <SyncPanel />
      </template>
      <template v-else-if="activeTab === 'debate'">
        <DebateLab />
      </template>
      <template v-else-if="activeTab === 'hermes'">
        <HermesChat />
      </template>
    </template>
  </AppLayout>
</template>

<style scoped>
.tab-nav {
  display: flex;
  gap: 4px;
}
.tab-btn {
  padding: 6px 16px;
  font-size: 0.8rem;
  color: #6b7280;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.tab-btn:hover {
  color: #d1d5db;
  background: #1f1f35;
}
.tab-btn.active {
  color: #f59e0b;
  background: #2a2a4a;
  border-color: #3a3a5e;
}
.sync-btn {
  padding: 6px 14px;
  font-size: 0.75rem;
  color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
.sync-btn:hover:not(:disabled) {
  background: rgba(34, 197, 94, 0.2);
  border-color: #22c55e;
}
.sync-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
