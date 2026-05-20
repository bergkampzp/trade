import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchMacroIndicators, fetchMacroSeries, fetchMacroNews } from '@/api/quant'
import type { MacroIndicatorSnapshot, MacroNewsItem } from '@/types'

export const useMacroStore = defineStore('macro', () => {
  const indicators = ref<MacroIndicatorSnapshot[]>([])
  const seriesData = ref<Record<string, [string, number][]>>({})
  const newsItems = ref<MacroNewsItem[]>([])
  const newsSummary = ref<Record<string, number>>({})
  const loading = ref(false)

  async function loadIndicators() {
    loading.value = true
    try {
      const res = await fetchMacroIndicators()
      indicators.value = res.indicators
    } finally {
      loading.value = false
    }
  }

  async function loadSeries(id: string) {
    if (seriesData.value[id]) return
    const res = await fetchMacroSeries(id)
    seriesData.value[id] = res.data
  }

  async function loadNews() {
    loading.value = true
    try {
      const res = await fetchMacroNews()
      newsItems.value = res.news
      newsSummary.value = res.summary
    } finally {
      loading.value = false
    }
  }

  return { indicators, seriesData, newsItems, newsSummary, loading, loadIndicators, loadSeries, loadNews }
})
