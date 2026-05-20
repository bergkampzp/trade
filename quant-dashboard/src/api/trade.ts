import { api } from './client'
import type {
  StrategyGenerateRequest,
  StrategyGenerateResponse,
  StrategyListResponse,
  StrategyDetail,
  BacktestRequest,
  BacktestProgressResponse,
  RankingResponse,
  ApprovalRecord,
  PaperStatusResponse,
  MonitorResponse,
  StrategyIterateResponse,
} from '@/types/trade'

// Strategy CRUD
export function generateStrategy(body: StrategyGenerateRequest) {
  return api<StrategyGenerateResponse>('/quant/strategies/generate', { method: 'POST', body })
}
export function listStrategies(limit = 20, offset = 0) {
  return api<StrategyListResponse>(`/quant/strategies?limit=${limit}&offset=${offset}`)
}
export function getStrategy(id: string) {
  return api<StrategyDetail>(`/quant/strategies/${id}`)
}

// Backtest
export function startBacktest(body: BacktestRequest) {
  return api<BacktestProgressResponse>('/quant/strategies/backtest', { method: 'POST', body })
}
export function getBacktestProgress(runId: string) {
  return api<BacktestProgressResponse>(`/quant/strategies/backtest/${runId}`)
}

// Ranking
export function getRanking(runId: string) {
  return api<RankingResponse>(`/quant/strategies/ranking?run_id=${runId}`)
}

// Approval
export function approveStrategy(id: string, comment?: string) {
  return api<ApprovalRecord>(`/quant/strategies/${id}/approve`, { method: 'POST', body: { comment } })
}
export function rejectStrategy(id: string, comment?: string) {
  return api<ApprovalRecord>(`/quant/strategies/${id}/reject`, { method: 'POST', body: { comment } })
}

// Paper Trading
export function startPaperTrading(id: string) {
  return api<PaperStatusResponse>(`/quant/strategies/${id}/start-paper`, { method: 'POST' })
}
export function stopPaperTrading(id: string) {
  return api<PaperStatusResponse>(`/quant/strategies/${id}/stop-paper`, { method: 'POST' })
}
export function getPaperStatus(id: string) {
  return api<PaperStatusResponse>(`/quant/strategies/${id}/paper-status`)
}

// Monitoring
export function getMonitor(id: string) {
  return api<MonitorResponse>(`/quant/strategies/${id}/monitor`)
}

// Iteration
export function iterateStrategy(id: string) {
  return api<StrategyIterateResponse>(`/quant/strategies/${id}/iterate`, { method: 'POST' })
}
