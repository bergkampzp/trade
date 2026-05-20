import { api } from './client'
import type {
  DebateRequest,
  DebateResponse,
  CnStockListResponse,
  CnKlineResponse,
} from '@/types/debate'

// A 股基础数据
export function fetchCnStockList() {
  return api<CnStockListResponse>('/quant/a-stocks')
}

export function fetchCnKline(stockCode: string, limit = 60) {
  return api<CnKlineResponse>(`/quant/a-stocks/${stockCode}?limit=${limit}`)
}

export function fetchCnLatest(stockCode: string) {
  return api<any>(`/quant/a-stocks/${stockCode}/latest`)
}

// Debate
export function runDebate(body: DebateRequest) {
  return api<DebateResponse>('/quant/debate', { method: 'POST', body })
}
