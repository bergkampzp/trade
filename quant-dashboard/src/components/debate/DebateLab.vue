<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useDebateStore } from '@/stores/debate'
import type { DebateStep } from '@/types/debate'

const store = useDebateStore()

const selectedCode = ref('000001')
const debateRounds = ref(1)
const showInput = ref(false)
const showSignal = ref(true)
const expandedSteps = ref<Set<number>>(new Set())
const activeView = ref<'process' | 'results'>('process')
const elapsedSeconds = ref(0)
let timerInterval: ReturnType<typeof setInterval> | null = null

const selectedName = computed(() => {
  const s = store.stocks.find(s => s.stock_code === selectedCode.value)
  return s?.stock_name || selectedCode.value
})

const latestPrice = computed(() => store.klineData[0]?.close ?? null)
const latestChange = computed(() => store.klineData[0]?.change_pct ?? null)

const ma5 = computed(() => {
  if (store.klineData.length < 5) return null
  return store.klineData.slice(0, 5).reduce((s, r) => s + r.close, 0) / 5
})
const ma20 = computed(() => {
  if (store.klineData.length < 20) return null
  return store.klineData.slice(0, 20).reduce((s, r) => s + r.close, 0) / 20
})

// Sparkline
const sparkData = computed(() => store.klineData.slice(0).reverse().map(r => r.close))
const sparkPath = computed(() => {
  const data = sparkData.value
  if (data.length < 2) return ''
  const mn = Math.min(...data), mx = Math.max(...data), rng = mx - mn || 1
  return 'M' + data.map((v, i) => {
    const x = (i / (data.length - 1)) * 200
    const y = 40 - ((v - mn) / rng) * 40
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' L')
})

function switchStock(code: string) {
  selectedCode.value = code
  store.selectStock(code)
}

async function doDebate() {
  elapsedSeconds.value = 0
  timerInterval = setInterval(() => { elapsedSeconds.value++ }, 1000)
  await store.startDebate(selectedCode.value, debateRounds.value)
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
  if (store.debateResult) {
    activeView.value = 'process'
  }
}

function toggleStep(idx: number) {
  if (expandedSteps.value.has(idx)) expandedSteps.value.delete(idx)
  else expandedSteps.value.add(idx)
}

function phaseIcon(phase: string) {
  const m: Record<string, string> = { bull: '🟢', bear: '🔴', manager: '🏆', trader: '💼', risk: '⚖️' }
  return m[phase] || '🔵'
}

function phaseLabel(phase: string) {
  const m: Record<string, string> = { bull: '看涨', bear: '看跌', manager: '裁决', trader: '交易员', risk: '风控' }
  return m[phase] || phase
}

function signalBadge(a: string) {
  const m: Record<string, string> = { buy: 'bg-green-600', sell: 'bg-red-600', hold: 'bg-yellow-600' }
  return m[a] || 'bg-gray-600'
}
function signalLabel(a: string) {
  const m: Record<string, string> = { buy: '买入', sell: '卖出', hold: '观望' }
  return m[a] || a
}

function fmtNum(n: number | null | undefined, d = 2) { return n == null ? '-' : n.toFixed(d) }
function fmtPct(n: number | null | undefined) { return n == null ? '-' : (n > 0 ? '+' : '') + n.toFixed(2) + '%' }

onMounted(() => {
  store.loadStocks()
  store.loadKline('000001')
})
</script>

<template>
  <div class="debate-lab">
    <div class="section-header">🧠 A 股多智能体辩论分析</div>

    <div class="layout">
      <!-- ===== Left: Data Panel ===== -->
      <div class="left">
        <div class="card">
          <div class="card-title">📈 选择股票</div>
          <div class="stock-grid">
            <button v-for="s in store.stocks" :key="s.stock_code"
              class="stock-btn" :class="{active: selectedCode === s.stock_code}"
              @click="switchStock(s.stock_code)">
              {{ s.stock_name }}<br><span class="text-2xs">{{ s.stock_code }}</span>
            </button>
          </div>
        </div>

        <div class="card" v-if="store.klineData.length">
          <div class="card-title">{{ selectedName }} 行情数据</div>
          <div class="price-bar">
            <span class="price-big">¥{{ fmtNum(latestPrice) }}</span>
            <span :class="(latestChange||0)>=0?'text-green-400':'text-red-400'">{{ fmtPct(latestChange) }}</span>
            <span class="text-xs text-gray-500">MA5:{{ fmtNum(ma5) }} MA20:{{ fmtNum(ma20) }}</span>
          </div>
          <svg viewBox="0 0 200 40" class="sparkline" v-if="sparkData.length > 2">
            <path :d="sparkPath" fill="none" stroke="#f59e0b" stroke-width="1.5"/>
          </svg>
          <div class="data-stats">
            <div class="stat">开盘: {{ fmtNum(store.klineData[0]?.open) }}</div>
            <div class="stat">最高: {{ fmtNum(store.klineData[0]?.high) }}</div>
            <div class="stat">最低: {{ fmtNum(store.klineData[0]?.low) }}</div>
            <div class="stat">成交量: {{ store.klineData[0]?.volume }}</div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">⚙️ 参数</div>
          <div class="control-row">
            <select v-model.number="debateRounds" class="input-sm">
              <option :value="1">1 轮 (快速, ~60秒)</option>
              <option :value="2">2 轮 (深度, ~120秒)</option>
              <option :value="3">3 轮 (全面, ~180秒)</option>
            </select>
            <button class="btn-debate" :disabled="store.debating" @click="doDebate">
              {{ store.debating ? '⏳ 分析中...' : '▶ 开始' }}
            </button>
          </div>
          <div v-if="store.error" class="error-msg">{{ store.error }}</div>
        </div>
      </div>

      <!-- ===== Right: Results ===== -->
      <div class="right">
        <!-- Loading — 真实时间指示器 -->
        <div v-if="store.debating" class="card loading-card">
          <div class="loading-content">
            <div class="spinner"></div>
            <div class="loading-text">
              <div class="loading-title">🤖 AI 多智能体辩论进行中</div>
              <div class="loading-desc">正在调用 DeepSeek LLM 推理，每轮约 15-30 秒...</div>
              <div class="loading-eta" id="debate-timer">⏱️ 已等待 {{ elapsedSeconds }} 秒 (约 30-90 秒完成)</div>
              <div class="loading-steps">
                <div class="load-step"><span class="step-num">1</span> 读取 A 股行情数据 <span class="step-status done">✅</span></div>
                <div class="load-step"><span class="step-num">2</span> 看涨分析师 (LLM推理) <span class="step-status busy">⟳</span></div>
                <div class="load-step"><span class="step-num">3</span> 看跌分析师 (LLM推理)</div>
                <div class="load-step"><span class="step-num">4</span> 研究经理综合裁决</div>
                <div class="load-step"><span class="step-num">5</span> 交易员最终决策</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Results -->
        <div v-if="store.debateResult && !store.debating" class="result-area">
          <!-- Signal Banner -->
          <div v-if="store.debateResult.trade_signal && showSignal" class="signal-banner"
               :class="signalBadge(store.debateResult.trade_signal.action)">
            <div class="signal-main">
              <span class="signal-action">{{ signalLabel(store.debateResult.trade_signal.action) }}</span>
              <span class="signal-conf">置信度 {{ ((store.debateResult.trade_signal.confidence||0)*100).toFixed(0) }}%</span>
              <span class="signal-risk">风险 {{ ((store.debateResult.trade_signal.risk_score||0)*100).toFixed(0) }}%</span>
            </div>
            <div class="signal-sub">
              <span v-if="store.debateResult.trade_signal.target_price">目标 ¥{{ store.debateResult.trade_signal.target_price.toFixed(2) }}</span>
              <span v-if="store.debateResult.trade_signal.stop_loss" class="ml-2">止损 ¥{{ store.debateResult.trade_signal.stop_loss.toFixed(2) }}</span>
              <span class="ml-2 text-2xs">{{ store.debateResult.trade_signal.time_horizon }}</span>
              <button class="ml-auto text-2xs btn-text" @click="showSignal=false">✕</button>
            </div>
          </div>

          <!-- View Switcher -->
          <div class="view-switcher">
            <button :class="{active: activeView==='process'}" @click="activeView='process'">📋 推理过程</button>
            <button :class="{active: activeView==='results'}" @click="activeView='results'">📊 三方观点</button>
          </div>

          <!-- ===== PROCESS VIEW ===== -->
          <div v-if="activeView==='process'" class="process-view">
            <!-- Input Data Summary -->
            <div class="card">
              <div class="card-title clickable" @click="showInput=!showInput">
                📥 输入数据 (引用来源) {{ showInput ? '▲' : '▼' }}
              </div>
              <div v-if="showInput" class="input-data-box">
                <div class="data-section">
                  <div class="data-title">📊 行情数据 ({{ store.klineData.length }}条)</div>
                  <table class="mini-table">
                    <tr><th>日期</th><th>收盘</th><th>涨跌幅</th><th>成交量</th></tr>
                    <tr v-for="r in store.klineData.slice(0,10)" :key="r.trade_date">
                      <td>{{ r.trade_date?.slice(5) }}</td>
                      <td>{{ r.close }}</td>
                      <td :class="(r.change_pct||0)>=0?'up':'dn'">{{ fmtPct(r.change_pct) }}</td>
                      <td class="text-2xs">{{ (r.volume/10000).toFixed(0) }}万</td>
                    </tr>
                  </table>
                </div>
                <div class="data-section">
                  <div class="data-title">📈 技术指标 (Agent 引用)</div>
                  <div class="data-tags">
                    <span v-for="dp in store.debateResult.process_log?.[0]?.key_data_points || []" :key="dp" class="tag">{{ dp }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Process Timeline -->
            <div class="timeline">
              <div v-for="(step, idx) in store.debateResult.process_log" :key="idx" class="tl-item"
                   :class="step.phase">
                <div class="tl-line"></div>
                <div class="tl-node">{{ phaseIcon(step.phase) }}</div>
                <div class="tl-card">
                  <div class="tl-header" @click="toggleStep(idx)">
                    <span class="tl-badge" :class="'badge-'+step.phase">
                      {{ phaseLabel(step.phase) }} #{{ step.round }}
                    </span>
                    <span class="tl-agent">{{ step.agent_name }}</span>
                    <span class="tl-toggle">{{ expandedSteps.has(idx) ? '收起 ▲' : '展开 ▼' }}</span>
                  </div>
                  <div class="tl-output">{{ step.summary || step.output?.slice(0,300) }}</div>
                  <div v-if="expandedSteps.has(idx)" class="tl-detail">
                    <div class="tl-section">
                      <div class="tl-section-title">📊 引用的关键数据</div>
                      <div class="tl-tags">
                        <span v-for="dp in step.key_data_points" :key="dp" class="tag">{{ dp }}</span>
                      </div>
                    </div>
                    <div class="tl-section">
                      <div class="tl-section-title">📝 完整输出</div>
                      <div class="tl-full-text">{{ step.output }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ===== RESULTS VIEW (三方观点) ===== -->
          <div v-if="activeView==='results'" class="results-view">
            <div class="three-cols">
              <div class="col col-bull">
                <div class="col-header">🟢 看涨观点 ({{ store.debateResult.bull_arguments.length }}轮)</div>
                <div v-for="(arg,i) in store.debateResult.bull_arguments" :key="i" class="col-arg">
                  <div class="col-round">第{{ i+1 }}轮</div>
                  <div class="col-text">{{ arg }}</div>
                </div>
              </div>
              <div class="col col-bear">
                <div class="col-header">🔴 看跌观点 ({{ store.debateResult.bear_arguments.length }}轮)</div>
                <div v-for="(arg,i) in store.debateResult.bear_arguments" :key="i" class="col-arg">
                  <div class="col-round">第{{ i+1 }}轮</div>
                  <div class="col-text">{{ arg }}</div>
                </div>
              </div>
              <div class="col col-verdict">
                <div class="col-header">🏆 综合裁决</div>
                <div class="col-arg">
                  <div class="col-round">研究经理</div>
                  <div class="col-text">{{ store.debateResult.research_manager_decision }}</div>
                </div>
                <div class="col-arg" v-if="store.debateResult.trader_decision">
                  <div class="col-round">交易员</div>
                  <div class="col-text">{{ store.debateResult.trader_decision }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Empty -->
        <div v-if="!store.debateResult && !store.debating" class="empty-state">
          <div class="text-5xl mb-3">🧠</div>
          <div class="text-gray-400 text-sm">选择 A 股，点击「开始」</div>
          <div class="text-gray-600 text-xs mt-2">5 Agent 辩论链: 看涨 → 看跌 → 研究经理 → 交易员</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.debate-lab {
  padding: 14px;
  overflow-y: auto;
  max-height: calc(100vh - 60px);
  color: #e5e7eb;
}
.section-header { font-size: 1.05rem; font-weight: 700; color: #f59e0b; margin-bottom: 14px; }

.layout { display: grid; grid-template-columns: 300px 1fr; gap: 14px; align-items: start; }
.left { display: flex; flex-direction: column; gap: 10px; }

/* Cards */
.card {
  background: #1a1a2e; border: 1px solid #2a2a4e; border-radius: 10px; padding: 12px;
}
.card-title { font-size: 0.82rem; font-weight: 600; margin-bottom: 8px; color: #d1d5db; }
.clickable { cursor: pointer; }
.clickable:hover { color: #f59e0b; }

/* Stocks */
.stock-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.stock-btn {
  padding: 6px 4px; font-size: 0.72rem; background: #0f0f1a; border: 1px solid #2a2a4e;
  border-radius: 6px; color: #9ca3af; cursor: pointer; text-align: center; line-height: 1.3;
}
.stock-btn:hover { border-color: #f59e0b; color: #e5e7eb; }
.stock-btn.active { background: #2a2a4a; border-color: #f59e0b; color: #f59e0b; }
.text-2xs { font-size: 0.6rem; }

/* Price */
.price-bar { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.price-big { font-size: 1.3rem; font-weight: 700; color: #f59e0b; }
.sparkline { width: 100%; height: 36px; margin-bottom: 4px; }
.data-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 3px; }
.stat { font-size: 0.7rem; color: #6b7280; }

/* Controls */
.control-row { display: flex; gap: 6px; }
.input-sm {
  flex: 1; background: #0f0f1a; border: 1px solid #2a2a4e; border-radius: 5px;
  padding: 5px 8px; color: #e5e7eb; font-size: 0.75rem;
}
.btn-debate {
  padding: 6px 14px; background: #f59e0b; color: #1a1a2e; border: none;
  border-radius: 6px; font-size: 0.78rem; font-weight: 600; cursor: pointer; white-space: nowrap;
}
.btn-debate:hover:not(:disabled) { opacity: 0.85; }
.btn-debate:disabled { opacity: 0.5; cursor: not-allowed; }

/* Loading */
.loading-card { padding: 24px; }
.loading-content { display: flex; gap: 16px; align-items: flex-start; }
.spinner {
  width: 36px; height: 36px; border: 3px solid #2a2a4e; border-top: 3px solid #f59e0b;
  border-radius: 50%; animation: spin 1s linear infinite; flex-shrink: 0; margin-top: 4px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { flex: 1; }
.loading-title { font-size: 0.9rem; font-weight: 600; color: #f59e0b; margin-bottom: 4px; }
.loading-desc { font-size: 0.72rem; color: #6b7280; margin-bottom: 6px; }
.loading-eta { font-size: 0.7rem; color: #4b5563; margin-bottom: 12px; }
.loading-steps { display: flex; flex-direction: column; gap: 6px; }
.load-step { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; color: #4b5563; }
.step-num {
  width: 18px; height: 18px; border-radius: 50%; background: #1f1f35;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.65rem; font-weight: 600; color: #6b7280;
}
.step-status { font-size: 0.7rem; }
.step-status.done { color: #22c55e; }
.step-status.busy { color: #f59e0b; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

/* Signal Banner */
.signal-banner {
  display: flex; flex-direction: column; gap: 4px;
  padding: 10px 14px; border-radius: 8px; margin-bottom: 10px; color: #fff;
}
.signal-banner.bg-green-600 { background: #16a34a; }
.signal-banner.bg-red-600 { background: #dc2626; }
.signal-banner.bg-yellow-600 { background: #ca8a04; }
.signal-main { display: flex; gap: 12px; align-items: center; }
.signal-action { font-size: 1rem; font-weight: 700; }
.signal-conf, .signal-risk { font-size: 0.75rem; opacity: 0.9; }
.signal-sub { display: flex; gap: 8px; font-size: 0.72rem; opacity: 0.85; }
.btn-text { background: none; border: none; color: #fff; cursor: pointer; opacity: 0.6; }
.btn-text:hover { opacity: 1; }

/* View Switcher */
.view-switcher { display: flex; gap: 4px; margin-bottom: 10px; }
.view-switcher button {
  flex: 1; padding: 6px; font-size: 0.75rem; border: 1px solid #2a2a4e;
  border-radius: 6px; background: #0f0f1a; color: #9ca3af; cursor: pointer;
}
.view-switcher button.active { background: #2a2a4a; border-color: #f59e0b; color: #f59e0b; }

/* Input Data */
.input-data-box { max-height: 300px; overflow-y: auto; }
.data-section { margin-bottom: 8px; }
.data-title { font-size: 0.72rem; font-weight: 600; color: #9ca3af; margin-bottom: 4px; }
.data-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.tag {
  padding: 2px 8px; background: #2a2a4a; border: 1px solid #3a3a5e;
  border-radius: 4px; font-size: 0.65rem; color: #94a3b8;
}
.mini-table { width: 100%; border-collapse: collapse; font-size: 0.65rem; }
.mini-table th { text-align: left; padding: 2px 4px; color: #6b7280; border-bottom: 1px solid #2a2a4e; }
.mini-table td { padding: 2px 4px; border-bottom: 1px solid #1f1f35; }
.up { color: #22c55e; }
.dn { color: #ef4444; }

/* Timeline */
.timeline { position: relative; }
.tl-item { display: flex; gap: 12px; margin-bottom: 10px; position: relative; }
.tl-line {
  position: absolute; left: 18px; top: 30px; bottom: -10px; width: 2px;
  background: #2a2a4e;
}
.tl-item:last-child .tl-line { display: none; }
.tl-node { font-size: 1.2rem; line-height: 1; padding-top: 2px; flex-shrink: 0; width: 36px; }
.tl-card { flex: 1; background: #0f0f1a; border: 1px solid #1f1f35; border-radius: 8px; padding: 10px; }
.tl-header { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.tl-header:hover { opacity: 0.8; }
.tl-badge {
  padding: 2px 8px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; color: #fff;
}
.badge-bull { background: #16a34a; }
.badge-bear { background: #dc2626; }
.badge-manager { background: #f59e0b; color: #1a1a2e; }
.badge-trader { background: #3b82f6; }
.tl-agent { font-size: 0.72rem; color: #9ca3af; flex: 1; }
.tl-toggle { font-size: 0.6rem; color: #6b7280; }
.tl-output { font-size: 0.75rem; color: #d1d5db; margin-top: 4px; line-height: 1.4; }
.tl-detail { margin-top: 8px; border-top: 1px solid #1f1f35; padding-top: 8px; }
.tl-section { margin-bottom: 8px; }
.tl-section-title { font-size: 0.68rem; font-weight: 600; color: #6b7280; margin-bottom: 4px; }
.tl-tags { display: flex; flex-wrap: wrap; gap: 3px; }
.tl-full-text { font-size: 0.72rem; color: #94a3b8; white-space: pre-wrap; line-height: 1.4; max-height: 300px; overflow-y: auto; }

/* Results (three columns) */
.three-cols { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.col { padding: 10px; border-radius: 8px; max-height: 500px; overflow-y: auto; }
.col-bull { background: rgba(22,163,74,0.06); border: 1px solid rgba(22,163,74,0.2); }
.col-bear { background: rgba(220,38,38,0.06); border: 1px solid rgba(220,38,38,0.2); }
.col-verdict { background: rgba(245,158,11,0.06); border: 1px solid rgba(245,158,11,0.2); }
.col-header { font-size: 0.78rem; font-weight: 600; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #2a2a4e; }
.col-arg { margin-bottom: 8px; }
.col-round { font-size: 0.65rem; color: #6b7280; margin-bottom: 2px; font-weight: 600; }
.col-text { font-size: 0.72rem; color: #d1d5db; line-height: 1.4; white-space: pre-wrap; }

/* Empty */
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 250px; text-align: center;
}

.error-msg {
  margin-top: 6px; padding: 6px; background: rgba(239,68,68,0.15);
  border: 1px solid rgba(239,68,68,0.3); border-radius: 6px; color: #ef4444; font-size: 0.7rem;
}

.text-green-400 { color: #22c55e; }
.text-red-400 { color: #ef4444; }
.text-gray-400 { color: #9ca3af; }
.text-gray-500 { color: #6b7280; }
.text-gray-600 { color: #4b5563; }
.ml-auto { margin-left: auto; }
.ml-2 { margin-left: 8px; }
.mb-2 { margin-bottom: 8px; }
.mb-3 { margin-bottom: 12px; }
</style>
