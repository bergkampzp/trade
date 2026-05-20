// ---- Data Sources ----
export interface DataSourcePair {
  pair: string
  row_count: number
  date_min: string
  date_max: string
}

export interface DataSourceGroup {
  name: string
  status: 'active' | 'coming_soon'
  pairs: DataSourcePair[]
}

export interface DataSourcesResponse {
  sources: DataSourceGroup[]
}

// ---- Factors ----
export interface FactorMetrics {
  ic_mean: number | null
  ic_ir: number | null
  quantile_sharpe: number | null
  backtest_sharpe: number | null
  backtest_max_dd: number | null
}

export interface FactorSummary {
  name: string
  bucket: string
  direction: string
  description: string
  zscore_column: string
  metrics: FactorMetrics
  verdict: string | null
}

export interface FactorsResponse {
  factors: FactorSummary[]
}

// ---- Factor Detail ----
export interface IcWindowStats {
  window: string
  ic_mean: number
  ic_std: number
  ic_ir: number
  ic_t_stat: number
  n_months: number
}

export interface QuantileBacktest {
  sharpe_annualized: number
  mean_ret_per_hour: number
  std_ret_per_hour: number
  total_return: number
  n_hours: number
}

export interface CorrelationEntry {
  factor_b: string
  corr_pearson: number
  n_obs: number
}

export interface FactorDetailResponse {
  name: string
  bucket: string
  direction: string
  description: string
  ic_by_window: IcWindowStats[]
  quantile_backtest: QuantileBacktest | null
  correlations: CorrelationEntry[]
}

// ---- Time Series ----
export interface MacroNewsItem {
  published_at: string
  source: string
  headline: string
  sentiment: string
  score: number
  summary: string
}

export interface MacroNewsResponse {
  news: MacroNewsItem[]
  summary: Record<string, number>
}

// ---- Correlation Matrix ----
export interface CorrelationMatrixResponse {
  factors: string[]
  matrix: number[][]
}

// ---- Trades ----
export interface TradeMarker {
  open_date: string
  close_date: string
  open_rate: number
  close_rate: number
  profit_pct: number
  exit_reason: string
  direction: string
}

export interface TradesResponse {
  trades: TradeMarker[]
}

// ---- Macro Indicators ----
export interface MacroIndicatorSnapshot {
  series_id: string
  name: string
  latest_value: number | null
  latest_date: string | null
  prev_value: number | null
  change_pct: number | null
  frequency: string
}

export interface MacroIndicatorsResponse {
  indicators: MacroIndicatorSnapshot[]
}

export interface MacroIndicatorSeriesResponse {
  series_id: string
  name: string
  data: [string, number][]
}

// ---- Macro News ----
export interface MacroNewsItem {
  published_at: string
  source: string
  headline: string
  sentiment: string
  score: number
  summary: string
}

// ---- Sync ----
export interface SyncStatusItem {
  source: string
  status: string
  last_sync: string | null
  last_result: string | null
  row_count: number
}

export interface SyncStatusResponse {
  sources: SyncStatusItem[]
}

export interface SyncLogItem {
  id: number
  source: string
  status: string
  records: number
  message: string
  started_at: string
  finished_at: string | null
}

export interface SyncLogsResponse {
  logs: SyncLogItem[]
}

export interface SyncResultResponse {
  source: string
  status: string
  records?: number
  duration_s?: number
  error?: string
}
