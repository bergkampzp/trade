<script setup lang="ts">
import { computed } from 'vue'
import { useMacroStore } from '@/stores/macro'

const store = useMacroStore()

interface Conclusion {
  title: string
  status: 'bullish' | 'bearish' | 'neutral'
  detail: string
}

const conclusions = computed<Conclusion[]>(() => {
  const inds = store.indicators
  if (!inds.length) return []

  const result: Conclusion[] = []

  // CPI analysis
  const cpi = inds.find(i => i.series_id === 'CPIAUCSL')
  if (cpi?.change_pct != null) {
    if (cpi.change_pct > 0.5) {
      result.push({
        title: 'CPI (Inflation)',
        status: 'bearish',
        detail: `MoM change +${cpi.change_pct}% — rising inflation pressures risk assets. Crypto may face short-term sell pressure as hawkish Fed expectations rise.`
      })
    } else if (cpi.change_pct < -0.5) {
      result.push({
        title: 'CPI (Inflation)',
        status: 'bullish',
        detail: `MoM change ${cpi.change_pct}% — disinflationary signal. Supports risk-on positioning for crypto assets.`
      })
    } else {
      result.push({
        title: 'CPI (Inflation)',
        status: 'neutral',
        detail: `Stable inflation at ${cpi.change_pct}% MoM. No immediate macro catalyst for crypto direction.`
      })
    }
  }

  // Treasury spread analysis
  const spread = inds.find(i => i.series_id === 'T10Y2Y')
  if (spread?.latest_value != null) {
    if (spread.latest_value < 0) {
      result.push({
        title: 'Yield Curve (10Y-2Y)',
        status: 'bearish',
        detail: `Spread at ${spread.latest_value}% — yield curve inverted. Historically precedes recession. Defensive positioning recommended; reduce crypto allocation.`
      })
    } else {
      result.push({
        title: 'Yield Curve (10Y-2Y)',
        status: 'bullish',
        detail: `Spread at ${spread.latest_value}% — curve normalized. Risk-on environment favorable for crypto.`
      })
    }
  }

  // VIX analysis
  const vix = inds.find(i => i.series_id === 'VIXCLS')
  if (vix?.latest_value != null) {
    if (vix.latest_value > 25) {
      result.push({
        title: 'VIX (Fear Index)',
        status: 'bearish',
        detail: `VIX at ${vix.latest_value} — elevated fear. Crypto historically sells off in high-VIX regimes. Reduce position size.`
      })
    } else if (vix.latest_value < 15) {
      result.push({
        title: 'VIX (Fear Index)',
        status: 'bullish',
        detail: `VIX at ${vix.latest_value} — low volatility regime. Favorable for trend-following crypto strategies.`
      })
    } else {
      result.push({
        title: 'VIX (Fear Index)',
        status: 'neutral',
        detail: `VIX at ${vix.latest_value} — moderate volatility. Standard risk management applies.`
      })
    }
  }

  // DXY analysis
  const dxy = inds.find(i => i.series_id === 'DTWEXBGS')
  if (dxy?.change_pct != null) {
    if (dxy.change_pct > 0.5) {
      result.push({
        title: 'DXY (Dollar Strength)',
        status: 'bearish',
        detail: `Dollar strengthening +${dxy.change_pct}%. Strong USD historically pressures BTC/ETH. Consider reducing crypto exposure.`
      })
    } else if (dxy.change_pct < -0.5) {
      result.push({
        title: 'DXY (Dollar Strength)',
        status: 'bullish',
        detail: `Dollar weakening ${dxy.change_pct}%. Weak USD provides tailwind for crypto assets.`
      })
    }
  }

  return result
})

const overallSignal = computed(() => {
  const bullish = conclusions.value.filter(c => c.status === 'bullish').length
  const bearish = conclusions.value.filter(c => c.status === 'bearish').length
  return { bullish, bearish, total: conclusions.value.length }
})

function statusColor(s: string) {
  if (s === 'bullish') return 'text-green-400 border-green-900 bg-green-900/20'
  if (s === 'bearish') return 'text-red-400 border-red-900 bg-red-900/20'
  return 'text-yellow-400 border-yellow-900 bg-yellow-900/20'
}

function statusLabel(s: string) {
  if (s === 'bullish') return '🟢 看多'
  if (s === 'bearish') return '🔴 看空'
  return '🟡 中性'
}
</script>

<template>
  <div class="analysis-panel">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-gray-300">宏观分析报告</h3>
      <div class="flex gap-2 text-xs">
        <span class="text-green-400">🟢 看多 {{ overallSignal.bullish }}</span>
        <span class="text-red-400">🔴 看空 {{ overallSignal.bearish }}</span>
        <span class="text-gray-500">/ {{ overallSignal.total }} 个因子</span>
      </div>
    </div>

    <!-- Overall signal bar -->
    <div class="signal-bar mb-4">
      <div class="flex justify-between text-xs text-gray-500 mb-1">
        <span>看空</span>
      <span class="text-xs">信号: {{ overallSignal.bullish - overallSignal.bearish }}</span>
        <span>看多</span>
      </div>
      <div class="bar-track">
        <div
          class="bar-fill"
          :style="{
            width: Math.abs(overallSignal.bullish - overallSignal.bearish) / overallSignal.total * 100 + '%',
            marginLeft: overallSignal.bearish > overallSignal.bullish ? '0' : (overallSignal.bearish / overallSignal.total * 100) + '%',
            background: overallSignal.bullish >= overallSignal.bearish
              ? 'linear-gradient(90deg, #f59e0b, #22c55e)'
              : 'linear-gradient(90deg, #ef4444, #f59e0b)'
          }"
        />
      </div>
    </div>

    <div v-if="!conclusions.length" class="text-center text-gray-600 py-8">
      选择因子查看分析
    </div>

    <div class="conclusion-list">
      <div
        v-for="c in conclusions"
        :key="c.title"
        class="conclusion-item"
        :class="statusColor(c.status)"
      >
        <div class="flex items-center justify-between mb-1">
          <span class="text-sm font-medium">{{ c.title }}</span>
          <span class="text-xs">{{ statusLabel(c.status) }}</span>
        </div>
        <p class="text-xs text-gray-400 leading-relaxed">{{ c.detail }}</p>
      </div>
    </div>

    <!-- Recommendation -->
    <div v-if="conclusions.length" class="mt-4 p-3 bg-[#1a1a2e] rounded border border-gray-700">
      <div class="text-sm font-medium text-amber-400 mb-1">
        {{ overallSignal.bullish > overallSignal.bearish ? '🟢 风险偏好建议' :
           overallSignal.bearish > overallSignal.bullish ? '🔴 风险回避建议' :
           '🟡 中性建议' }}
      </div>
      <p class="text-xs text-gray-400">
        {{ overallSignal.bullish > overallSignal.bearish
           ? '宏观环境利好风险资产。考虑适度增加加密资产仓位，设置止损。'
           : overallSignal.bearish > overallSignal.bullish
           ? '宏观逆风信号较多。建议降低仓位、增加现金，等待信号明确。'
           : '宏观信号混杂。维持当前仓位，等待方向性信号。' }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.analysis-panel {
  padding: 16px;
  overflow-y: auto;
}
.signal-bar {
  background: #0f0f1a;
  border-radius: 8px;
  padding: 12px;
}
.bar-track {
  height: 6px;
  background: #1f1f35;
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: all 0.5s ease;
}
.conclusion-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conclusion-item {
  border: 1px solid;
  border-radius: 8px;
  padding: 12px;
}
</style>
