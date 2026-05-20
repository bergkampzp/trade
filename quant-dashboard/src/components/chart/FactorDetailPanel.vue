<script setup lang="ts">
import { computed } from 'vue'
import { useQuantStore } from '@/stores/quant'

const store = useQuantStore()
const detail = computed(() => store.factorDetail)
const qbt = computed(() => detail.value?.quantile_backtest)

function fmtNum(v: number | null | undefined, decimals = 4): string {
  if (v == null) return '-'
  return v.toFixed(decimals)
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '-'
  return (v * 100).toFixed(1) + '%'
}
</script>

<template>
  <div class="p-4 overflow-y-auto detail-panel">
    <div v-if="!store.selectedFactor" class="text-gray-600 text-center py-8">
      选择一个因子查看详情
    </div>
    <template v-else-if="detail">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-base font-semibold text-gray-200">{{ detail.name }}</h3>
        <span class="text-xs px-2 py-0.5 rounded"
              :class="detail.bucket === 'A' ? 'bg-green-900 text-green-300' : 'bg-blue-900 text-blue-300'">
          Bucket {{ detail.bucket }}
        </span>
      </div>
      <p class="text-xs text-gray-500 mb-4">{{ detail.description }}</p>

      <!-- IC by Window -->
      <div class="mb-4" v-if="detail.ic_by_window.length">
        <h4 class="text-xs font-semibold text-gray-400 uppercase mb-2">IC Analysis</h4>
        <div class="grid grid-cols-3 gap-2">
          <div v-for="w in detail.ic_by_window" :key="w.window"
               class="bg-[#1a1a2e] rounded p-2">
            <div class="text-xs text-gray-500">{{ w.window }}</div>
            <div class="text-sm font-medium">{{ fmtNum(w.ic_mean) }}</div>
            <div class="text-xs text-gray-500">
              IR: {{ fmtNum(w.ic_ir, 2) }} | t: {{ fmtNum(w.ic_t_stat, 2) }}
            </div>
          </div>
        </div>
      </div>

      <!-- Quantile Backtest -->
      <div class="mb-4" v-if="qbt">
        <h4 class="text-xs font-semibold text-gray-400 uppercase mb-2">Quantile Backtest</h4>
        <div class="grid grid-cols-3 gap-2">
          <div class="metric-card">
            <div class="label">Sharpe</div>
            <div class="value">{{ fmtNum(qbt.sharpe_annualized, 2) }}</div>
          </div>
          <div class="metric-card">
            <div class="label">Total Return</div>
            <div class="value">{{ fmtPct(qbt.total_return) }}</div>
          </div>
          <div class="metric-card">
            <div class="label">Hours</div>
            <div class="value">{{ qbt.n_hours }}</div>
          </div>
        </div>
      </div>

      <!-- Correlations -->
      <div v-if="detail.correlations.length">
        <h4 class="text-xs font-semibold text-gray-400 uppercase mb-2">Correlations</h4>
        <div class="space-y-1">
          <div v-for="c in detail.correlations" :key="c.factor_b"
               class="flex items-center justify-between text-xs">
            <span class="text-gray-400">{{ c.factor_b }}</span>
            <span :class="Math.abs(c.corr_pearson) > 0.7 ? 'text-red-400' : 'text-gray-500'">
              {{ c.corr_pearson.toFixed(3) }}
            </span>
          </div>
        </div>
      </div>
    </template>
    <div v-else-if="store.loading.factorDetail" class="text-center text-gray-600 py-8 animate-pulse">
      Loading...
    </div>
  </div>
</template>

<style scoped>
.detail-panel {
  flex: 4;
  min-height: 150px;
}
.metric-card {
  background: #1a1a2e;
  border-radius: 6px;
  padding: 8px;
}
.metric-card .label {
  font-size: 0.7rem;
  color: #6b7280;
}
.metric-card .value {
  font-size: 0.875rem;
  font-weight: 600;
  color: #d1d5db;
}
</style>
