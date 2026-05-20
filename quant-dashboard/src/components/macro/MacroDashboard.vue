<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useMacroStore } from '@/stores/macro'

const store = useMacroStore()

const indicatorGrid = computed(() => store.indicators.slice(0, 6))

function trendClass(v: number | null) {
  if (v == null) return 'text-gray-500'
  if (v > 0) return 'text-green-400'
  if (v < 0) return 'text-red-400'
  return 'text-yellow-400'
}

function trendIcon(v: number | null) {
  if (v == null) return '→'
  if (v > 0) return '▲'
  if (v < 0) return '▼'
  return '→'
}

onMounted(() => {
  store.loadIndicators().catch(() => {})
})
</script>

<template>
  <div class="macro-dashboard">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-gray-300">宏观数据看板</h3>
      <span class="text-xs text-gray-500">数据源: FRED / yfinance</span>
    </div>

    <div v-if="!indicatorGrid.length && !store.loading" class="text-center text-gray-600 py-12">
      暂无宏观数据
    </div>

    <div class="indicator-grid">
      <div
        v-for="ind in indicatorGrid"
        :key="ind.series_id"
        class="indicator-card"
      >
        <div class="text-xs text-gray-500 truncate" :title="ind.name">{{ ind.name }}</div>
        <div class="text-2xl font-bold text-gray-100 mt-1">
          {{ ind.latest_value?.toLocaleString() ?? '-' }}
        </div>
        <div class="flex items-center gap-1 mt-1">
          <span class="text-xs" :class="trendClass(ind.change_pct)">
            {{ trendIcon(ind.change_pct) }} {{ ind.change_pct != null ? Math.abs(ind.change_pct).toFixed(1) + '%' : '-' }}
          </span>
          <span class="text-xs text-gray-600 ml-auto">{{ ind.frequency }}</span>
        </div>
        <div class="text-xs text-gray-600 mt-1">{{ ind.latest_date ?? '-' }}</div>
      </div>
    </div>

    <!-- Correlation hint -->
    <div class="mt-4 p-3 bg-[#1a1a2e] rounded text-xs text-gray-500">
      <span class="text-gray-400">BTC 相关性 (最新):</span>
      CPI: {{ store.indicators[0]?.change_pct != null ? (store.indicators[0].change_pct > 0 ? '📈 看多 (风险偏好)' : '📉 看空 (通胀压力)') : 'N/A' }}
      <span class="mx-2">|</span>
      VIX: {{ store.indicators[2]?.latest_value != null ? (store.indicators[2].latest_value! > 20 ? '⚠ 偏高' : '✓ 适中') : 'N/A' }}
      <span class="mx-2">|</span>
      利差: {{ store.indicators[4]?.latest_value != null ? (store.indicators[4].latest_value! < 0 ? '⚠ 倒挂' : '✓ 正常') : 'N/A' }}
    </div>
  </div>
</template>

<style scoped>
.macro-dashboard {
  padding: 16px;
}
.indicator-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.indicator-card {
  background: #1a1a2e;
  border-radius: 8px;
  padding: 14px;
  border: 1px solid #2a2a3e;
  transition: border-color 0.2s;
}
.indicator-card:hover {
  border-color: #3a3a4e;
}
</style>
