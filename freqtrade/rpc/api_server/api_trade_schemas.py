"""Pydantic schemas for the v4.0 AI Trading Module API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Strategy Generation
# ---------------------------------------------------------------------------


class StrategyGenerateRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000, description="自然语言策略描述")
    trading_pair: str = Field(
        ..., pattern=r"^[A-Z0-9]+/[A-Z0-9]+$", description="交易对，如 BTC/USDT"
    )
    max_factors: int = Field(default=5, ge=1, le=8, description="最大引用因子数")

    @field_validator("description")
    @classmethod
    def no_html_injection(cls, v: str) -> str:
        import re

        if re.search(r"<[^>]+>", v):
            raise ValueError("HTML tags not allowed")
        return v


class StrategyGenerateResponse(BaseModel):
    strategy_id: UUID
    name: str
    code: str
    description: str
    trading_pair: str
    status: str


# ---------------------------------------------------------------------------
# Strategy CRUD
# ---------------------------------------------------------------------------


class StrategySummary(BaseModel):
    strategy_id: UUID
    strategy_version_id: UUID
    version: int
    name: str
    description: Optional[str] = None
    trading_pair: str
    timeframe: str
    status: str
    created_at: str
    updated_at: str


class StrategyDetail(StrategySummary):
    code: str
    factor_ids: Optional[list[str]] = None


class StrategyListResponse(BaseModel):
    strategies: list[StrategySummary]
    total: int


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    strategy_ids: list[UUID] = Field(..., min_length=1, max_length=5)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class BacktestWindowResult(BaseModel):
    window_type: str  # in_sample | validation | out_of_sample
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    deflated_sharpe: Optional[float] = None
    total_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    total_trades: Optional[int] = None
    avg_hold_hours: Optional[float] = None
    profit_factor: Optional[float] = None


class BacktestResultItem(BaseModel):
    strategy_id: UUID
    strategy_name: str
    run_id: UUID
    status: str  # running | completed | failed
    error_message: Optional[str] = None
    windows: list[BacktestWindowResult]
    overfit_flag: bool = False  # IS_Sharpe / OOS_Sharpe > 1.5


class BacktestProgressResponse(BaseModel):
    run_id: UUID
    status: str  # queued | running | completed | failed
    total: int
    completed: int
    results: list[BacktestResultItem]


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class RankedStrategy(BaseModel):
    rank: int
    strategy_id: UUID
    strategy_name: str
    deflated_sharpe: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    total_return_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    oos_sharpe: Optional[float] = None
    overfit_flag: bool = False
    status: str


class RankingResponse(BaseModel):
    run_id: UUID
    strategies: list[RankedStrategy]


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    comment: Optional[str] = None


class ApprovalRecord(BaseModel):
    id: int
    strategy_id: UUID
    action: str
    comment: Optional[str] = None
    approved_by: str
    created_at: str


# ---------------------------------------------------------------------------
# Paper Trading
# ---------------------------------------------------------------------------


class PaperTradeRecord(BaseModel):
    id: int
    strategy_id: UUID
    trade_id: str
    trading_pair: str
    direction: str
    open_date: str
    close_date: Optional[str] = None
    open_rate: float
    close_rate: Optional[float] = None
    amount: float
    profit_pct: Optional[float] = None
    profit_abs: Optional[float] = None
    exit_reason: Optional[str] = None


class PaperStatusResponse(BaseModel):
    strategy_id: UUID
    status: str  # not_started | running | stopped | error
    systemd_unit: Optional[str] = None
    pid: Optional[int] = None
    started_at: Optional[str] = None
    open_positions: int = 0
    total_pnl: Optional[float] = None


class MonitorResponse(BaseModel):
    strategy_id: UUID
    strategy_name: str
    status: str
    open_positions: list[dict]
    closed_trades: list[PaperTradeRecord]
    cumulative_pnl: list[dict]  # [{date, pnl}, ...]
    max_drawdown_30d: Optional[float] = None
    sharpe_30d: Optional[float] = None
    win_rate_30d: Optional[float] = None
    daily_returns: list[dict]  # [{date, return_pct}, ...]


# ---------------------------------------------------------------------------
# Daily Report
# ---------------------------------------------------------------------------


class DailyReportResponse(BaseModel):
    id: int
    report_date: str
    report_content: str
    total_pnl: Optional[float] = None
    win_rate_pct: Optional[float] = None
    total_trades: Optional[int] = None
    sharpe_30d: Optional[float] = None
    max_drawdown: Optional[float] = None
    created_at: str


class DailyReportListResponse(BaseModel):
    reports: list[DailyReportResponse]


# ---------------------------------------------------------------------------
# Strategy Iteration
# ---------------------------------------------------------------------------


class StrategyIterateResponse(BaseModel):
    original_id: UUID
    new_strategy_id: UUID
    new_version: int
    suggestions: str
    code: str
