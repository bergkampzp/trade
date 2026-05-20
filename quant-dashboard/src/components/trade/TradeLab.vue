<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useTradeStore } from '@/stores/trade'
import { useQuantStore } from '@/stores/quant'
import type { BacktestResultItem, RankedStrategy } from '@/types/trade'

const store = useTradeStore()
const quantStore = useQuantStore()

const desc = ref('')
const pair = ref('BTC/USDT')
const maxFactors = ref(5)
const generateError = ref('')
const generatedCode = ref('')
const selectedForBacktest = ref<Set<string>>(new Set())
const polling = ref<ReturnType<typeof setInterval> | null>(null)

const pairs = computed(() =>
  quantStore.dataSources?.[0]?.pairs?.map((p: any) => p.pair) || ['BTC/USDT']
)

function toggleSelectStrategy(id: string) {
  if (selectedForBacktest.value.has(id)) {
    selectedForBacktest.value.delete(id)
  } else {
    if (selectedForBacktest.value.size >= 5) return
    selectedForBacktest.value.add(id)
  }
}

async function doGenerate() {
  if (!desc.value.trim()) return
  generateError.value = ''
  try {
    const res = await store.generateStrategy({
      description: desc.value,
      trading_pair: pair.value,
      max_factors: maxFactors.value,
    })
    generatedCode.value = res.code
    desc.value = ''
  } catch (e: any) {
    generateError.value = e?.data?.detail || e?.message || '生成失败'
  }
}

async function doBacktest() {
  if (selectedForBacktest.value.size === 0) return
  await store.startBacktest(Array.from(selectedForBacktest.value))
  // Start polling
  polling.value = setInterval(() => store.pollBacktest(), 2000)
}

function stopPolling() {
  if (polling.value) {
    clearInterval(polling.value)
    polling.value = null
  }
}

// Status badge color
function statusColor(s: string) {
  const map: Record<string, string> = {
    draft: 'bg-gray-600',
    pending_review: 'bg-yellow-600',
    approved: 'bg-green-600',
    rejected: 'bg-red-600',
    active: 'bg-blue-600',
    stopped: 'bg-gray-500',
    archived: 'bg-gray-700',
  }
  return map[s] || 'bg-gray-600'
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    draft: '草稿',
    pending_review: '待审批',
    approved: '已批准',
    rejected: '已拒绝',
    active: '运行中',
    stopped: '已停止',
    archived: '已归档',
  }
  return map[s] || s
}

function fmtNum(n: number | null | undefined, decimals = 2): string {
  if (n == null) return '-'
  return n.toFixed(decimals)
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '-'
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%'
}

async function doApprove(id: string) {
  try {
    const { approveStrategy } = await import('@/api/trade')
    await approveStrategy(id)
    await store.loadStrategies()
  } catch {}
}

async function doReject(id: string) {
  try {
    const { rejectStrategy } = await import('@/api/trade')
    await rejectStrategy(id)
    await store.loadStrategies()
  } catch {}

}

onMounted(() => {
  store.loadStrategies()
})

// Cleanup polling on unmount
import { onUnmounted } from 'vue'
onUnmounted(stopPolling)
</script>

<template>
  <div class="trade-lab">
    <!-- Header -->
    <div class="section-header">策略实验室</div>

    <!-- Section 1: Strategy Generation -->
    <div class="card">
      <div class="card-title">🤖 AI 策略生成</div>
      <div class="form-row">
        <textarea
          v-model="desc"
          placeholder="描述你的交易策略，例如：当 BTC 动量强且成交量放大时做多，止损-5%..."
          rows="3"
          class="input-area"
        />
        <div class="form-options">
          <select v-model="pair" class="input-select">
            <option v-for="p in pairs" :key="p" :value="p">{{ p }}</option>
          </select>
          <input v-model.number="maxFactors" type="number" min="1" max="8" class="input-num" />
          <span class="text-xs text-gray-500">因子数</span>
          <button
            class="btn-primary"
            :disabled="store.generating || !desc.trim()"
            @click="doGenerate"
          >
            {{ store.generating ? '⏳ 生成中...' : '⚡ 生成策略' }}
          </button>
        </div>
      </div>
      <div v-if="generateError" class="error-msg">{{ generateError }}</div>
      <div v-if="generatedCode" class="code-block">
        <div class="code-label">✅ 策略已生成并存入数据库</div>
        <pre>{{ generatedCode.slice(0, 500) }}{{ generatedCode.length > 500 ? '...' : '' }}</pre>
      </div>
    </div>

    <!-- Section 2: Strategy List -->
    <div class="card">
      <div class="card-title">📋 策略列表 ({{ store.total }})</div>
      <button
        v-if="selectedForBacktest.size > 0"
        class="btn-primary mb-2"
        :disabled="store.backtesting"
        @click="doBacktest"
      >
        🔬 回测选中策略 ({{ selectedForBacktest.size }})
      </button>
      <div v-if="store.backtesting" class="text-sm text-yellow-400 mb-2">
        ⏳ 回测进行中... {{ store.backtestProgress?.completed || 0 }}/{{ store.backtestProgress?.total || 0 }}
      </div>
      <table class="data-table" v-if="store.strategies.length">
        <thead>
          <tr>
            <th>选</th>
            <th>名称</th>
            <th>交易对</th>
            <th>状态</th>
            <th>版本</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in store.strategies" :key="s.strategy_id">
            <td>
              <input
                type="checkbox"
                :checked="selectedForBacktest.has(s.strategy_id)"
                @change="toggleSelectStrategy(s.strategy_id)"
              />
            </td>
            <td class="name-cell">{{ s.name }}</td>
            <td>{{ s.trading_pair }}</td>
            <td><span class="badge" :class="statusColor(s.status)">{{ statusLabel(s.status) }}</span></td>
            <td>v{{ s.version }}</td>
            <td class="text-xs text-gray-500">{{ s.created_at?.slice(0, 10) }}</td>
            <td class="actions-cell">
              <button
                v-if="s.status === 'pending_review'"
                class="btn-xs btn-approve"
                @click="doApprove(s.strategy_id)"
              >批准</button>
              <button
                v-if="s.status === 'pending_review'"
                class="btn-xs btn-reject"
                @click="doReject(s.strategy_id)"
              >拒绝</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="text-gray-500 text-sm py-4">暂无策略，使用上方 AI 生成器创建</div>
    </div>

    <!-- Section 3: Backtest Results -->
    <div v-if="store.backtestProgress?.results?.length" class="card">
      <div class="card-title">📊 回测结果</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>策略</th>
            <th>窗口</th>
            <th>Sharpe</th>
            <th>最大回撤</th>
            <th>总收益</th>
            <th>胜率</th>
            <th>交易次数</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="r in store.backtestProgress.results" :key="r.strategy_id">
            <tr v-for="w in r.windows" :key="r.strategy_id + w.window_type">
              <td :rowspan="r.windows.length" v-if="w === r.windows[0]" class="name-cell">
                {{ r.strategy_name }}
                <span v-if="r.overfit_flag" class="text-xs text-red-400 ml-1">⚠️过拟合</span>
              </td>
              <td>{{ w.window_type === 'in_sample' ? '样本内' : w.window_type === 'validation' ? '验证集' : '样本外' }}</td>
              <td>{{ fmtNum(w.sharpe_ratio) }}</td>
              <td>{{ fmtPct(w.max_drawdown_pct) }}</td>
              <td>{{ fmtPct(w.total_return_pct) }}</td>
              <td>{{ fmtPct(w.win_rate_pct) }}</td>
              <td>{{ w.total_trades ?? '-' }}</td>
              <td>{{ r.status }}</td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- Section 4: Ranking -->
    <div v-if="store.rankings.length" class="card">
      <div class="card-title">🏆 策略排名 (Deflated Sharpe)</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>排名</th>
            <th>策略</th>
            <th>DSR</th>
            <th>Sharpe</th>
            <th>样本外 Sharpe</th>
            <th>最大回撤</th>
            <th>总收益</th>
            <th>胜率</th>
            <th>过拟合</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in store.rankings" :key="r.strategy_id">
            <td class="font-bold">{{ r.rank }}</td>
            <td class="name-cell">{{ r.strategy_name }}</td>
            <td>{{ fmtNum(r.deflated_sharpe) }}</td>
            <td>{{ fmtNum(r.sharpe_ratio) }}</td>
            <td>{{ fmtNum(r.oos_sharpe) }}</td>
            <td>{{ fmtPct(r.max_drawdown_pct) }}</td>
            <td>{{ fmtPct(r.total_return_pct) }}</td>
            <td>{{ fmtPct(r.win_rate_pct) }}</td>
            <td>
              <span v-if="r.overfit_flag" class="text-red-400">⚠️</span>
              <span v-else class="text-green-400">✓</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.trade-lab {
  padding: 16px;
  overflow-y: auto;
  max-height: calc(100vh - 60px);
}
.section-header {
  font-size: 1.1rem;
  font-weight: 700;
  color: #f59e0b;
  margin-bottom: 16px;
}
.card {
  background: #1a1a2e;
  border: 1px solid #2a2a4e;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 16px;
}
.card-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: #e5e7eb;
  margin-bottom: 12px;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-options {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.input-area {
  width: 100%;
  background: #0f0f1a;
  border: 1px solid #2a2a4e;
  border-radius: 6px;
  padding: 10px;
  color: #e5e7eb;
  font-size: 0.8rem;
  resize: vertical;
}
.input-area:focus {
  outline: none;
  border-color: #f59e0b;
}
.input-select, .input-num {
  background: #0f0f1a;
  border: 1px solid #2a2a4e;
  border-radius: 6px;
  padding: 6px 10px;
  color: #e5e7eb;
  font-size: 0.8rem;
}
.input-num {
  width: 60px;
}
.btn-primary {
  padding: 8px 18px;
  background: #f59e0b;
  color: #1a1a2e;
  border: none;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-primary:hover:not(:disabled) {
  opacity: 0.85;
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-xs {
  padding: 3px 10px;
  border: none;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  margin-right: 4px;
}
.btn-approve {
  background: #22c55e;
  color: #1a1a2e;
}
.btn-reject {
  background: #ef4444;
  color: #fff;
}
.error-msg {
  margin-top: 8px;
  padding: 8px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  color: #ef4444;
  font-size: 0.75rem;
}
.code-block {
  margin-top: 12px;
}
.code-label {
  font-size: 0.75rem;
  color: #22c55e;
  margin-bottom: 6px;
}
.code-block pre {
  background: #0d0d1a;
  border: 1px solid #1a1a3e;
  border-radius: 6px;
  padding: 10px;
  font-size: 0.7rem;
  color: #94a3b8;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}
.data-table th {
  text-align: left;
  padding: 6px 8px;
  color: #6b7280;
  font-weight: 600;
  border-bottom: 1px solid #2a2a4e;
}
.data-table td {
  padding: 6px 8px;
  color: #d1d5db;
  border-bottom: 1px solid #1f1f35;
}
.name-cell {
  color: #f59e0b;
  font-weight: 500;
}
.badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.65rem;
  color: #fff;
}
.actions-cell {
  white-space: nowrap;
}
.mb-2 {
  margin-bottom: 8px;
}
</style>
