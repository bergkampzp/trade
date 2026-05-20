<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuantStore } from '@/stores/quant'
import type { FactorSummary } from '@/types'

const store = useQuantStore()
const sortKey = ref<'ic_mean' | 'ic_ir' | 'backtest_sharpe'>('backtest_sharpe')

const sorted = computed(() => {
  const list = [...store.factors]
  list.sort((a, b) => {
    const va = a.metrics[sortKey.value] ?? -Infinity
    const vb = b.metrics[sortKey.value] ?? -Infinity
    return vb - va
  })
  return list
})

function verdictColor(v: string | null) {
  if (!v) return 'text-gray-500'
  if (v === 'PASS') return 'text-green-400'
  if (v === 'REVIEW') return 'text-yellow-400'
  return 'text-red-400'
}

function onSelect(f: FactorSummary) {
  store.selectFactor(f.name)
}
</script>

<template>
  <div class="p-3">
    <div class="flex items-center justify-between mb-2">
      <h3 class="text-xs font-semibold uppercase text-gray-400">因子列表</h3>
      <select
        v-model="sortKey"
        class="text-xs bg-transparent border border-gray-600 rounded px-1 py-0.5 text-gray-400"
      >
        <option value="backtest_sharpe">夏普比率</option>
        <option value="ic_mean">IC 均值</option>
        <option value="ic_ir">IC 信息比</option>
      </select>
    </div>
    <div
      v-for="f in sorted"
      :key="f.name"
      class="factor-item"
      :class="{ active: store.selectedFactor === f.name }"
      @click="onSelect(f)"
    >
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium">{{ f.name }}</span>
        <span class="text-xs" :class="verdictColor(f.verdict)">{{ f.verdict || '-' }}</span>
      </div>
      <div class="flex gap-3 text-xs text-gray-500 mt-0.5">
        <span>IC: {{ f.metrics.ic_mean?.toFixed(4) ?? '-' }}</span>
        <span>Sharpe: {{ f.metrics.backtest_sharpe?.toFixed(2) ?? '-' }}</span>
        <span>DD: {{ f.metrics.backtest_max_dd != null ? (f.metrics.backtest_max_dd * 100).toFixed(1) + '%' : '-' }}</span>
      </div>
      <div class="text-xs text-gray-600 mt-0.5">{{ f.description }}</div>
    </div>
  </div>
</template>

<style scoped>
.factor-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}
.factor-item:hover {
  background: #1f1f35;
}
.factor-item.active {
  background: #2a2a4a;
  border-left: 3px solid #f59e0b;
}
</style>
