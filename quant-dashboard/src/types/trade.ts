// ---- v4.0 Trade Types ----

export interface StrategyGenerateRequest {
  description: string
  trading_pair: string
  max_factors: number
}

export interface StrategyGenerateResponse {
  strategy_id: string
  name: string
  code: string
  description: string
  trading_pair: string
  status: string
}

export interface StrategySummary {
  strategy_id: string
  strategy_version_id: string
  version: number
  name: string
  description: string | null
  trading_pair: string
  timeframe: string
  status: string
  created_at: string
  updated_at: string
}

export interface StrategyDetail extends StrategySummary {
  code: string
  factor_ids: string[] | null
}

export interface StrategyListResponse {
  strategies: StrategySummary[]
  total: number
}

export interface BacktestRequest {
  strategy_ids: string[]
  start_date?: string
  end_date?: string
}

export interface BacktestWindowResult {
  window_type: string
  sharpe_ratio: number | null
  sortino_ratio: number | null
  deflated_sharpe: number | null
  total_return_pct: number | null
  max_drawdown_pct: number | null
  win_rate_pct: number | null
  total_trades: number | null
}

export interface BacktestResultItem {
  strategy_id: string
  strategy_name: string
  run_id: string
  status: string
  error_message: string | null
  windows: BacktestWindowResult[]
  overfit_flag: boolean
}

export interface BacktestProgressResponse {
  run_id: string
  status: string
  total: number
  completed: number
  results: BacktestResultItem[]
}

export interface RankedStrategy {
  rank: number
  strategy_id: string
  strategy_name: string
  deflated_sharpe: number | null
  sharpe_ratio: number | null
  max_drawdown_pct: number | null
  total_return_pct: number | null
  win_rate_pct: number | null
  oos_sharpe: number | null
  overfit_flag: boolean
  status: string
}

export interface RankingResponse {
  run_id: string
  strategies: RankedStrategy[]
}

export interface ApprovalRecord {
  id: number
  strategy_id: string
  action: string
  comment: string | null
  approved_by: string
  created_at: string
}

export interface PaperStatusResponse {
  strategy_id: string
  status: string
  systemd_unit?: string
  pid?: number
  started_at?: string
  open_positions: number
  total_pnl?: number
}

export interface MonitorResponse {
  strategy_id: string
  strategy_name: string
  status: string
  open_positions: Record<string, any>[]
  closed_trades: any[]
  cumulative_pnl: any[]
  max_drawdown_30d: number | null
  sharpe_30d: number | null
  win_rate_30d: number | null
  daily_returns: any[]
}

export interface StrategyIterateResponse {
  original_id: string
  new_strategy_id: string
  new_version: number
  suggestions: string
  code: string
}
