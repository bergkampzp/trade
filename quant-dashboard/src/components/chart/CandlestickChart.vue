<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { useQuantStore } from '@/stores/quant'
import { useChart } from '@/composables/useChart'

const store = useQuantStore()
const containerRef = ref<HTMLElement | null>(null)
const { setOhlcvData, setZscoreOverlay, setTradeMarkers, dispose } = useChart(containerRef)

watch(() => store.ohlcv, (v) => setOhlcvData(v))
watch(() => store.factorZscores, (v) => setZscoreOverlay(v))
watch(() => store.trades, (v) => setTradeMarkers(v))

onUnmounted(() => dispose())
</script>

<template>
  <div class="chart-area">
    <div class="chart-placeholder"
         v-if="!store.selectedPair && !store.loading.ohlcv">
      选择交易对查看行情
    </div>
    <div ref="containerRef" class="chart-container" />
    <div v-if="store.loading.ohlcv" class="loading-indicator">
      加载中...
    </div>
  </div>
</template>

<style scoped>
.chart-area {
  position: relative;
  flex: 6;
  min-height: 300px;
  overflow: hidden;
}
.chart-container {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
}
.chart-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #4b5563;
  z-index: 1;
}
.loading-indicator {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 0.75rem;
  color: #f59e0b;
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
