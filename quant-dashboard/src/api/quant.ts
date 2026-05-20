import { api } from './client'
import type {
  CorrelationMatrixResponse,
  DataSourcesResponse,
  FactorDetailResponse,
  FactorsResponse,
  MacroIndicatorsResponse,
  MacroIndicatorSeriesResponse,
  MacroNewsResponse,
  SyncStatusResponse,
  SyncLogsResponse,
  SyncResultResponse,
  TimeSeriesResponse,
  TradesResponse,
} from '@/types'

export function fetchDataSources() { return api<DataSourcesResponse>('/quant/data-sources') }
export function fetchFactors() { return api<FactorsResponse>('/quant/factors') }
export function fetchFactorDetail(name: string) { return api<FactorDetailResponse>(`/quant/factors/${name}`) }
export function fetchOhlcv(pair: string, start: string, end: string) { return api<TimeSeriesResponse>('/quant/ohlcv', { query: { pair, start, end } }) }
export function fetchFactorZscore(pair: string, factor: string, start: string, end: string) { return api<TimeSeriesResponse>('/quant/factor-zscore', { query: { pair, factor, start, end } }) }
export function fetchIcRolling(factor: string) { return api<TimeSeriesResponse>('/quant/ic-rolling', { query: { factor } }) }
export function fetchFactorCorrelation() { return api<CorrelationMatrixResponse>('/quant/factor-correlation') }
export function fetchNav(factor: string) { return api<TimeSeriesResponse>('/quant/nav', { query: { factor } }) }
export function fetchTrades(pair: string, factor: string) { return api<TradesResponse>('/quant/trades', { query: { pair, factor } }) }

// Macro endpoints
export function fetchMacroIndicators() { return api<MacroIndicatorsResponse>('/quant/macro-indicators') }
export function fetchMacroSeries(id: string) { return api<MacroIndicatorSeriesResponse>(`/quant/macro-indicators/${id}`) }
export function fetchMacroNews() { return api<MacroNewsResponse>('/quant/macro-news') }

// Sync endpoints
export function fetchSyncStatus(lang = 'zh_CN') { return api<SyncStatusResponse>(`/quant/sync/status?lang=${lang}`) }
export function fetchSyncLogs() { return api<SyncLogsResponse>('/quant/sync/logs') }
export function triggerSync(source: string) { return api<SyncResultResponse>(`/quant/sync/${source}`, { method: 'POST' }) }
