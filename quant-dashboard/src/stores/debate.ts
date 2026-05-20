import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  DebateResponse,
  CnStockItem,
  CnKlineItem,
  TradeSignal,
} from '@/types/debate'
import {
  fetchCnStockList,
  fetchCnKline,
  runDebate,
} from '@/api/debate'

export const useDebateStore = defineStore('debate', () => {
  // State
  const stocks = ref<CnStockItem[]>([])
  const klineData = ref<CnKlineItem[]>([])
  const selectedStock = ref<string>('000001')
  const loading = ref(false)
  const debating = ref(false)
  const debateResult = ref<DebateResponse | null>(null)
  const error = ref('')

  // Actions
  async function loadStocks() {
    try {
      const res = await fetchCnStockList()
      stocks.value = res.stocks
    } catch (e: any) {
      error.value = '加载A股列表失败: ' + (e.message || e)
    }
  }

  async function loadKline(ticker?: string) {
    const code = ticker || selectedStock.value
    try {
      const res = await fetchCnKline(code, 60)
      klineData.value = res.data
      selectedStock.value = res.stock_code
    } catch (e: any) {
      error.value = '加载K线数据失败: ' + (e.message || e)
    }
  }

  async function startDebate(ticker: string, rounds = 2) {
    debating.value = true
    error.value = ''
    debateResult.value = null
    try {
      const res = await runDebate({
        ticker,
        debate_rounds: rounds,
      })
      debateResult.value = res
      return res
    } catch (e: any) {
      error.value = '辩论分析失败: ' + (e?.data?.detail || e?.message || e)
      return null
    } finally {
      debating.value = false
    }
  }

  function selectStock(code: string) {
    selectedStock.value = code
    loadKline(code)
  }

  return {
    stocks, klineData, selectedStock, loading, debating,
    debateResult, error,
    loadStocks, loadKline, startDebate, selectStock,
  }
})
