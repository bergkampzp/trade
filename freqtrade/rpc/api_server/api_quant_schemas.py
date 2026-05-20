"""Pydantic schemas for the Quant Dashboard API."""

from __future__ import annotations

from pydantic import BaseModel


# --- Data Sources ---


class DataSourcePair(BaseModel):
    pair: str
    row_count: int
    date_min: str | None = None
    date_max: str | None = None


class DataSourceGroup(BaseModel):
    name: str
    status: str  # "active" | "coming_soon"
    pairs: list[DataSourcePair]


class DataSourcesResponse(BaseModel):
    sources: list[DataSourceGroup]


# --- Factors ---


class FactorMetrics(BaseModel):
    ic_mean: float | None = None
    ic_ir: float | None = None
    quantile_sharpe: float | None = None
    backtest_sharpe: float | None = None
    backtest_max_dd: float | None = None


class FactorSummary(BaseModel):
    name: str
    bucket: str
    direction: str
    description: str
    zscore_column: str
    metrics: FactorMetrics
    verdict: str | None = None


class FactorsResponse(BaseModel):
    factors: list[FactorSummary]


class IcWindowStats(BaseModel):
    window: str
    ic_mean: float | None = None
    ic_std: float | None = None
    ic_ir: float | None = None
    ic_t_stat: float | None = None
    n_months: int | None = None


class QuantileBacktest(BaseModel):
    sharpe_annualized: float | None = None
    mean_ret_per_hour: float | None = None
    std_ret_per_hour: float | None = None
    total_return: float | None = None
    n_hours: int | None = None


class CorrelationEntry(BaseModel):
    factor_b: str
    corr_pearson: float
    n_obs: int | None = None


class FactorDetailResponse(BaseModel):
    name: str
    bucket: str
    direction: str
    description: str
    ic_by_window: list[IcWindowStats]
    quantile_backtest: QuantileBacktest | None = None
    correlations: list[CorrelationEntry]


# --- Time Series ---


class TimeSeriesResponse(BaseModel):
    columns: list[str]
    data: list[list]


# --- Correlation Matrix ---


class CorrelationMatrixResponse(BaseModel):
    factors: list[str]
    matrix: list[list[float]]


# --- Trades ---


class TradeMarker(BaseModel):
    open_date: str
    close_date: str | None = None
    open_rate: float
    close_rate: float | None = None
    profit_pct: float | None = None
    exit_reason: str | None = None
    direction: str = "long"


class TradesResponse(BaseModel):
    trades: list[TradeMarker]


# --- Macro Indicators ---


class MacroIndicatorSnapshot(BaseModel):
    series_id: str
    name: str
    latest_value: float | None = None
    latest_date: str | None = None
    prev_value: float | None = None
    change_pct: float | None = None
    frequency: str = "monthly"


class MacroIndicatorsResponse(BaseModel):
    indicators: list[MacroIndicatorSnapshot]


class MacroIndicatorSeriesResponse(BaseModel):
    series_id: str
    name: str
    data: list[list]  # [[date, value], ...]


class MacroNewsItem(BaseModel):
    published_at: str
    source: str
    headline: str
    sentiment: str
    score: float
    summary: str = ""


class MacroNewsResponse(BaseModel):
    news: list[MacroNewsItem]
    summary: dict  # {positive: N, negative: N, neutral: N}
