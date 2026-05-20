import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import {
  fetchDataSources,
  fetchFactors,
  fetchFactorDetail,
  fetchOhlcv,
  fetchFactorZscore,
  fetchIcRolling,
  fetchNav,
  fetchTrades,
} from '@/api/quant'
import type {
  DataSourceGroup,
  FactorSummary,
  FactorDetailResponse,
  TimeSeriesResponse,
  TradeMarker,
} from '@/types'

function dateToCompact(dateStr: string): string {
  // "2025-04-10 00:00:00+00" -> "20250410"
  return dateStr.slice(0, 10).replace(/-/g, '')
}

export const useQuantStore = defineStore('quant', () => {
  // --- State ---
  const selectedPair = ref<string | null>(null)
  const selectedFactor = ref<string | null>(null)
  const timerange = ref({ start: '20250101', end: '20260410' })

  const dataSources = ref<DataSourceGroup[]>([])
  const factors = ref<FactorSummary[]>([])
  const factorDetail = ref<FactorDetailResponse | null>(null)

  const ohlcv = ref<TimeSeriesResponse | null>(null)
  const factorZscores = ref<TimeSeriesResponse | null>(null)
  const trades = ref<TradeMarker[]>([])
  const navCurve = ref<TimeSeriesResponse | null>(null)
  const icRolling = ref<TimeSeriesResponse | null>(null)

  const loading = ref<Record<string, boolean>>({})

  // --- Helpers ---
  function updateTimerangeForPair(pair: string) {
    for (const group of dataSources.value) {
      const found = group.pairs.find((p) => p.pair === pair)
      if (found) {
        timerange.value = {
          start: dateToCompact(found.date_min),
          end: dateToCompact(found.date_max),
        }
        return
      }
    }
  }

  // --- Actions ---
  async function loadDataSources() {
    loading.value.dataSources = true
    try {
      const res = await fetchDataSources()
      dataSources.value = res.sources
    } finally {
      loading.value.dataSources = false
    }
  }

  async function loadFactors() {
    loading.value.factors = true
    try {
      const res = await fetchFactors()
      factors.value = res.factors
    } finally {
      loading.value.factors = false
    }
  }

  async function loadOhlcv() {
    if (!selectedPair.value) return
    loading.value.ohlcv = true
    try {
      ohlcv.value = await fetchOhlcv(
        selectedPair.value,
        timerange.value.start,
        timerange.value.end,
      )
    } finally {
      loading.value.ohlcv = false
    }
  }

  async function loadTrades() {
    if (!selectedPair.value || !selectedFactor.value) return
    loading.value.trades = true
    try {
      const res = await fetchTrades(selectedPair.value, selectedFactor.value)
      trades.value = res.trades
    } catch {
      trades.value = []
    } finally {
      loading.value.trades = false
    }
  }

  async function loadFactorDetail() {
    if (!selectedFactor.value) return
    loading.value.factorDetail = true
    try {
      factorDetail.value = await fetchFactorDetail(selectedFactor.value)
    } finally {
      loading.value.factorDetail = false
    }
  }

  async function loadFactorZscore() {
    if (!selectedPair.value || !selectedFactor.value) return
    loading.value.zscore = true
    try {
      factorZscores.value = await fetchFactorZscore(
        selectedPair.value,
        selectedFactor.value,
        timerange.value.start,
        timerange.value.end,
      )
    } finally {
      loading.value.zscore = false
    }
  }

  async function loadIcRolling() {
    if (!selectedFactor.value) return
    loading.value.icRolling = true
    try {
      icRolling.value = await fetchIcRolling(selectedFactor.value)
    } finally {
      loading.value.icRolling = false
    }
  }

  async function loadNav() {
    if (!selectedFactor.value) return
    loading.value.nav = true
    try {
      navCurve.value = await fetchNav(selectedFactor.value)
    } finally {
      loading.value.nav = false
    }
  }

  function selectPair(pair: string) {
    selectedPair.value = pair
    updateTimerangeForPair(pair)
  }

  /** 强制刷新当前选中的图表数据（同步完成后调用） */
  function refreshCurrentData() {
    if (selectedPair.value) {
      updateTimerangeForPair(selectedPair.value)
      loadOhlcv()
      loadFactorZscore()
      loadTrades()
    }
  }

  function selectFactor(name: string) {
    selectedFactor.value = name
  }

  // --- Watchers ---
  watch(selectedPair, () => {
    loadOhlcv()
    loadTrades()
    loadFactorZscore()
  })

  watch(selectedFactor, () => {
    loadFactorDetail()
    loadFactorZscore()
    loadIcRolling()
    loadNav()
    loadTrades()
  })

  return {
    selectedPair,
    selectedFactor,
    timerange,
    dataSources,
    factors,
    factorDetail,
    ohlcv,
    factorZscores,
    trades,
    navCurve,
    icRolling,
    loading,
    loadDataSources,
    loadFactors,
    loadOhlcv,
    loadTrades,
    loadFactorDetail,
    loadFactorZscore,
    loadIcRolling,
    loadNav,
    selectPair,
    selectFactor,
    refreshCurrentData,
  }
})
