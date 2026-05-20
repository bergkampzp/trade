<script setup lang="ts">
import { computed } from 'vue'
import { useQuantStore } from '@/stores/quant'

const store = useQuantStore()

const treeData = computed(() =>
  store.dataSources.map((group) => ({
    label: group.name,
    disabled: group.status === 'coming_soon',
    children: group.pairs.map((p) => ({
      label: p.pair,
      meta: `${p.row_count} 行 | ${p.date_min?.slice(0, 10)} ~ ${p.date_max?.slice(0, 10)}`,
    })),
  })),
)

function onSelect(pair: string) {
  store.selectPair(pair)
}
</script>

<template>
  <div class="p-3">
    <h3 class="text-xs font-semibold uppercase text-gray-400 mb-2">数据源</h3>
    <div v-for="group in treeData" :key="group.label" class="mb-3">
      <div class="text-sm font-medium mb-1" :class="group.disabled ? 'text-gray-600' : 'text-gray-300'">
        {{ group.label }}
        <span v-if="group.disabled" class="text-xs text-gray-600 ml-1">即将上线</span>
      </div>
      <div v-if="!group.disabled">
        <div
          v-for="child in group.children"
          :key="child.label"
          class="pair-item"
          :class="{ active: store.selectedPair === child.label }"
          @click="onSelect(child.label)"
        >
          <span class="text-sm">{{ child.label }}</span>
          <span class="text-xs text-gray-500">{{ child.meta }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pair-item {
  display: flex;
  flex-direction: column;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.pair-item:hover {
  background: #1f1f35;
}
.pair-item.active {
  background: #2a2a4a;
  border-left: 3px solid #f59e0b;
}
</style>
