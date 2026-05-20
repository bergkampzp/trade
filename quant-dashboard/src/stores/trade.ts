import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  StrategySummary,
  StrategyDetail,
  StrategyGenerateRequest,
  StrategyGenerateResponse,
  BacktestResultItem,
  BacktestProgressResponse,
  RankedStrategy,
  RankingResponse,
} from '@/types/trade'
import * as tradeApi from '@/api/trade'

export const useTradeStore = defineStore('trade', () => {
  // State
  const strategies = ref<StrategySummary[]>([])
  const total = ref(0)
  const loading = ref(false)
  const generating = ref(false)
  const lastGenerated = ref<StrategyGenerateResponse | null>(null)

  // Backtest state
  const backtesting = ref(false)
  const backtestRunId = ref<string | null>(null)
  const backtestProgress = ref<BacktestProgressResponse | null>(null)

  // Ranking state
  const rankings = ref<RankedStrategy[]>([])
  const rankRunId = ref<string | null>(null)

  // Selected
  const selectedStrategy = ref<StrategyDetail | null>(null)

  // Actions
  async function loadStrategies(limit = 20, offset = 0) {
    loading.value = true
    try {
      const res = await tradeApi.listStrategies(limit, offset)
      strategies.value = res.strategies
      total.value = res.total
    } finally {
      loading.value = false
    }
  }

  async function generateStrategy(req: StrategyGenerateRequest) {
    generating.value = true
    try {
      const res = await tradeApi.generateStrategy(req)
      lastGenerated.value = res
      // Refresh list
      await loadStrategies()
      return res
    } finally {
      generating.value = false
    }
  }

  async function loadStrategyDetail(id: string) {
    loading.value = true
    try {
      selectedStrategy.value = await tradeApi.getStrategy(id)
      return selectedStrategy.value
    } finally {
      loading.value = false
    }
  }

  async function startBacktest(strategyIds: string[]) {
    backtesting.value = true
    try {
      const res = await tradeApi.startBacktest({ strategy_ids: strategyIds })
      backtestRunId.value = res.run_id
      return res
    } finally {
      backtesting.value = false
    }
  }

  async function pollBacktest() {
    if (!backtestRunId.value) return
    try {
      const res = await tradeApi.getBacktestProgress(backtestRunId.value)
      backtestProgress.value = res
      if (res.status === 'completed') {
        backtesting.value = false
        // Auto-load ranking
        rankRunId.value = backtestRunId.value
        await loadRanking()
      }
      return res
    } catch {
      // continue polling
    }
  }

  async function loadRanking() {
    if (!backtestRunId.value) return
    try {
      const res = await tradeApi.getRanking(backtestRunId.value)
      rankings.value = res.strategies
    } catch {
      // ignore
    }
  }

  return {
    strategies, total, loading, generating, lastGenerated,
    backtesting, backtestRunId, backtestProgress,
    rankings, rankRunId,
    selectedStrategy,
    loadStrategies, generateStrategy, loadStrategyDetail,
    startBacktest, pollBacktest, loadRanking,
  }
})
