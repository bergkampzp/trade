// ---- v4.0 Debate Types ----

export interface DebateRequest {
  ticker: string
  date?: string
  provider?: string
  model?: string
  debate_rounds?: number
}

export interface TradeSignal {
  action: string      // buy | sell | hold
  ticker: string
  confidence: number
  risk_score: number
  target_price: number | null
  stop_loss: number | null
  time_horizon: string
  reasoning_summary: string
}

export interface DebateStep {
  phase: string        // bull | bear | manager | trader | risk
  round: number
  agent_name: string
  input_context: string
  key_data_points: string[]
  output: string
  summary: string
}

export interface DebateResponse {
  status: string
  ticker: string
  analysis_date: string
  stock_name?: string
  latest_price?: number | null
  input_market_data?: string
  trade_signal: TradeSignal | null
  bull_arguments: string[]
  bear_arguments: string[]
  research_manager_decision: string
  risk_manager_decision?: string
  trader_decision: string
  process_log?: DebateStep[]
}

export interface CnStockItem {
  stock_code: string
  stock_name: string
}

export interface CnStockListResponse {
  stocks: CnStockItem[]
}

export interface CnKlineItem {
  stock_code: string
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  change_pct?: number
}

export interface CnKlineResponse {
  stock_code: string
  stock_name: string
  data: CnKlineItem[]
}
