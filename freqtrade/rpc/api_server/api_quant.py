"""Quant Dashboard API — factor research endpoints."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated

import requests
import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import HTTPException

from freqtrade.rpc.api_server.api_quant_schemas import (
    CorrelationEntry,
    CorrelationMatrixResponse,
    DataSourceGroup,
    DataSourcePair,
    DataSourcesResponse,
    FactorDetailResponse,
    FactorMetrics,
    FactorsResponse,
    FactorSummary,
    IcWindowStats,
    MacroIndicatorSeriesResponse,
    MacroIndicatorSnapshot,
    MacroIndicatorsResponse,
    MacroNewsItem,
    MacroNewsResponse,
    QuantileBacktest,
    TimeSeriesResponse,
    TradeMarker,
    TradesResponse,
)
from freqtrade.rpc.api_server.deps import get_quant_db
from freqtrade.rpc.api_server.quant_db import QuantDB
from freqtrade.rpc.api_server.translation import (
    translate_factors,
    translate_indicators,
    translate_sync_status,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["quant"])

_DEFAULT_FACTORS_YML = str(Path(__file__).resolve().parents[3] / "user_data" / "factors.yml")

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_DATA_SOURCES_SQL = """
    SELECT pair, COUNT(*) as row_count,
           MIN(date)::text as date_min, MAX(date)::text as date_max
    FROM quant_raw.ohlcv_crypto
    GROUP BY pair
    ORDER BY pair
"""

_SCOREBOARD_SQL = """
    SELECT factor_name, ic_mean, ic_ir, quantile_sharpe,
           backtest_sharpe, backtest_max_dd, verdict
    FROM quant.mart_factor_scoreboard
    WHERE run_date = (SELECT MAX(run_date) FROM quant.mart_factor_scoreboard)
"""

_IC_EXTENDED_SQL = """
    SELECT window_label, ic_mean, ic_std, ic_ir, ic_t_stat, n_months
    FROM quant.mart_factor_ic_extended
    WHERE factor_name = %s
    ORDER BY CASE window_label
        WHEN 'overall' THEN 0 WHEN 'last_12m' THEN 1 WHEN 'last_6m' THEN 2
    END
"""

_QUANTILE_BT_SQL = """
    SELECT sharpe_annualized, mean_ret_per_hour, std_ret_per_hour,
           total_return, n_hours
    FROM quant.mart_factor_quantile_backtest
    WHERE factor_name = %s
"""

_CORRELATION_SQL = """
    SELECT
        CASE WHEN factor_a = %s THEN factor_b ELSE factor_a END AS factor_b,
        corr_pearson, n_obs
    FROM quant.mart_factor_correlation
    WHERE (factor_a = %s OR factor_b = %s) AND factor_a <> factor_b
    ORDER BY ABS(corr_pearson) DESC
"""

_OHLCV_SQL = """
    SELECT date::text, open, high, low, close, volume
    FROM quant_raw.ohlcv_crypto
    WHERE pair = %s AND date >= %s::timestamp AND date < %s::timestamp
    ORDER BY date
"""

_FACTOR_ZSCORE_SQL = """
    SELECT date::text, zscore
    FROM quant.mart_factor_values_long
    WHERE pair = %s AND factor_name = %s
      AND date >= %s::timestamp AND date < %s::timestamp
    ORDER BY date
"""

_IC_ROLLING_SQL = """
    SELECT TO_CHAR(month, 'YYYY-MM') AS month,
           monthly_ic, rolling_3m_ic, rolling_3m_ic_std
    FROM quant.mart_factor_ic_rolling
    WHERE factor_name = %s
    ORDER BY month
"""

_CORR_MATRIX_SQL = """
    SELECT factor_a, factor_b, corr_pearson
    FROM quant.mart_factor_correlation
    UNION ALL
    SELECT factor_b AS factor_a, factor_a AS factor_b, corr_pearson
    FROM quant.mart_factor_correlation
    WHERE factor_a <> factor_b
    ORDER BY 1, 2
"""

_NAV_SQL = """
    SELECT date::text, nav
    FROM quant.mart_backtest_nav
    WHERE run_id LIKE 'sprint2_' || %s || '%%'
    ORDER BY date
"""

_TRADES_SQL = """
    SELECT open_date::text, close_date::text, open_rate, close_rate,
           profit_pct, exit_reason, 'long' as direction
    FROM quant.mart_backtest_trades
    WHERE pair = %s AND run_id LIKE 'sprint2_' || %s || '%%'
    ORDER BY open_date
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_db(db: QuantDB | None) -> QuantDB:
    if db is None:
        raise HTTPException(status_code=503, detail="PostgreSQL (quant_db) not configured")
    return db


def _parse_timerange(start: str, end: str) -> tuple[str, str]:
    """Convert '20250101', '20250401' to ('2025-01-01', '2025-04-01')."""

    def fmt(s: str) -> str:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    return fmt(start), fmt(end)


# ---------------------------------------------------------------------------
# Business logic (testable without FastAPI)
# ---------------------------------------------------------------------------


def _get_data_sources(db: QuantDB | None) -> DataSourcesResponse:
    pairs: list[DataSourcePair] = []
    if db is not None:
        rows = db.query_rows(_DATA_SOURCES_SQL)
        pairs = [DataSourcePair(**r) for r in rows]
    return DataSourcesResponse(
        sources=[
            DataSourceGroup(name="Crypto", status="active", pairs=pairs),
            DataSourceGroup(name="US Stocks", status="coming_soon", pairs=[]),
            DataSourceGroup(name="A-Shares", status="coming_soon", pairs=[]),
        ]
    )


def _get_factors(
    db: QuantDB | None, factors_yml_path: str = _DEFAULT_FACTORS_YML
) -> FactorsResponse:
    with Path(factors_yml_path).open() as f:
        registry = yaml.safe_load(f).get("factors", [])

    scoreboard: dict[str, dict] = {}
    if db is not None:
        for row in db.query_rows(_SCOREBOARD_SQL):
            scoreboard[row["factor_name"]] = row

    factors = []
    for entry in registry:
        sb = scoreboard.get(entry["name"], {})
        factors.append(
            FactorSummary(
                name=entry["name"],
                bucket=entry["bucket"],
                direction=entry["direction"],
                description=entry["description"],
                zscore_column=entry["zscore_column"],
                metrics=FactorMetrics(
                    ic_mean=sb.get("ic_mean"),
                    ic_ir=sb.get("ic_ir"),
                    quantile_sharpe=sb.get("quantile_sharpe"),
                    backtest_sharpe=sb.get("backtest_sharpe"),
                    backtest_max_dd=sb.get("backtest_max_dd"),
                ),
                verdict=sb.get("verdict"),
            )
        )
    return FactorsResponse(factors=factors)


def _get_factor_detail(
    name: str,
    db: QuantDB | None,
    factors_yml_path: str = _DEFAULT_FACTORS_YML,
) -> FactorDetailResponse:
    with Path(factors_yml_path).open() as f:
        registry = yaml.safe_load(f).get("factors", [])
    entry = next((e for e in registry if e["name"] == name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Factor '{name}' not found in registry")

    ic_windows: list[IcWindowStats] = []
    qbt: QuantileBacktest | None = None
    corrs: list[CorrelationEntry] = []

    if db is not None:
        for row in db.query_rows(_IC_EXTENDED_SQL, (name,)):
            ic_windows.append(
                IcWindowStats(
                    window=row["window_label"],
                    ic_mean=row["ic_mean"],
                    ic_std=row["ic_std"],
                    ic_ir=row["ic_ir"],
                    ic_t_stat=row["ic_t_stat"],
                    n_months=row["n_months"],
                )
            )

        qbt_rows = db.query_rows(_QUANTILE_BT_SQL, (name,))
        if qbt_rows:
            qbt = QuantileBacktest(**qbt_rows[0])

        for row in db.query_rows(_CORRELATION_SQL, (name, name, name)):
            corrs.append(CorrelationEntry(**row))

    return FactorDetailResponse(
        name=entry["name"],
        bucket=entry["bucket"],
        direction=entry["direction"],
        description=entry["description"],
        ic_by_window=ic_windows,
        quantile_backtest=qbt,
        correlations=corrs,
    )


def _get_ohlcv(db: QuantDB | None, pair: str, start: str, end: str) -> TimeSeriesResponse:
    db = _require_db(db)
    start_d, end_d = _parse_timerange(start, end)
    rows = db.query_rows(_OHLCV_SQL, (pair, start_d, end_d))
    columns = ["date", "open", "high", "low", "close", "volume"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


def _get_factor_zscore(
    db: QuantDB | None, pair: str, factor: str, start: str, end: str
) -> TimeSeriesResponse:
    db = _require_db(db)
    start_d, end_d = _parse_timerange(start, end)
    rows = db.query_rows(_FACTOR_ZSCORE_SQL, (pair, factor, start_d, end_d))
    columns = ["date", "zscore"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


def _get_ic_rolling(db: QuantDB | None, factor: str) -> TimeSeriesResponse:
    db = _require_db(db)
    rows = db.query_rows(_IC_ROLLING_SQL, (factor,))
    columns = ["month", "monthly_ic", "rolling_3m_ic", "rolling_3m_ic_std"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


def _get_factor_correlation(db: QuantDB | None) -> CorrelationMatrixResponse:
    db = _require_db(db)
    rows = db.query_rows(_CORR_MATRIX_SQL)
    factors_set: set[str] = set()
    corr_map: dict[tuple[str, str], float] = {}
    for r in rows:
        fa, fb = r["factor_a"], r["factor_b"]
        factors_set.add(fa)
        factors_set.add(fb)
        corr_map[(fa, fb)] = float(r["corr_pearson"])
    factors = sorted(factors_set)
    matrix = []
    for fa in factors:
        row = []
        for fb in factors:
            if fa == fb:
                row.append(1.0)
            else:
                row.append(corr_map.get((fa, fb), 0.0))
        matrix.append(row)
    return CorrelationMatrixResponse(factors=factors, matrix=matrix)


def _get_nav(db: QuantDB | None, factor: str) -> TimeSeriesResponse:
    db = _require_db(db)
    rows = db.query_rows(_NAV_SQL, (factor,))
    columns = ["date", "nav"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


def _get_trades(db: QuantDB | None, pair: str, factor: str) -> TradesResponse:
    db = _require_db(db)
    rows = db.query_rows(_TRADES_SQL, (pair, factor))
    trades = [TradeMarker(**r) for r in rows]
    return TradesResponse(trades=trades)


# ---------------------------------------------------------------------------
# Macro indicators
# ---------------------------------------------------------------------------

_MACRO_NAMES = {
    "CPIAUCSL": "CPI (Consumer Price Index)",
    "FEDFUNDS": "Fed Funds Rate",
    "VIXCLS": "VIX (Volatility Index)",
    "DTWEXBGS": "DXY (US Dollar Index)",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "INDPRO": "Industrial Production",
}

_MACRO_SNAPSHOT_SQL = """
    SELECT series_id, date, value
    FROM quant_raw.macro_indicators
    WHERE series_id = ANY(%s)
    ORDER BY series_id, date DESC
"""

_MACRO_SERIES_SQL = """
    SELECT date::text, value
    FROM quant_raw.macro_indicators
    WHERE series_id = %s AND date >= %s::timestamp
    ORDER BY date
"""

_NEWS_LATEST_SQL = """
    SELECT published_at::text, source, headline, sentiment, score, COALESCE(summary, '') as summary
    FROM quant_raw.news_sentiment
    ORDER BY published_at DESC
    LIMIT 30
"""

_NEWS_SUMMARY_SQL = """
    SELECT sentiment, COUNT(*) as cnt
    FROM quant_raw.news_sentiment
    WHERE published_at >= NOW() - INTERVAL '7 days'
    GROUP BY sentiment
"""


def _get_macro_indicators(db: QuantDB | None) -> MacroIndicatorsResponse:
    db = _require_db(db)
    series_ids = list(_MACRO_NAMES.keys())
    rows = db.query_rows(_MACRO_SNAPSHOT_SQL, (series_ids,))

    by_series: dict[str, list] = {}
    for r in rows:
        by_series.setdefault(r["series_id"], []).append(r)

    indicators = []
    for sid in series_ids:
        vals = by_series.get(sid, [])
        latest = vals[0] if vals else None
        prev = vals[1] if len(vals) > 1 else None

        change = None
        if latest and prev and prev["value"]:
            change = round(
                (float(latest["value"]) - float(prev["value"])) / float(prev["value"]) * 100,
                1,
            )

        indicators.append(
            MacroIndicatorSnapshot(
                series_id=sid,
                name=_MACRO_NAMES.get(sid, sid),
                latest_value=round(float(latest["value"]), 2) if latest else None,
                latest_date=str(latest["date"])[:10] if latest else None,
                prev_value=round(float(prev["value"]), 2) if prev else None,
                change_pct=change,
                frequency="daily" if sid in ("VIXCLS", "DTWEXBGS", "T10Y2Y") else "monthly",
            )
        )
    return MacroIndicatorsResponse(indicators=indicators)


def _get_macro_series(
    db: QuantDB | None, series_id: str, start: str = "2023-01-01"
) -> MacroIndicatorSeriesResponse:
    db = _require_db(db)
    rows = db.query_rows(_MACRO_SERIES_SQL, (series_id, start))
    data = [[r["date"], float(r["value"])] for r in rows]
    return MacroIndicatorSeriesResponse(
        series_id=series_id,
        name=_MACRO_NAMES.get(series_id, series_id),
        data=data,
    )


def _get_macro_news(db: QuantDB | None) -> MacroNewsResponse:
    db = _require_db(db)
    rows = db.query_rows(_NEWS_LATEST_SQL)
    news = [
        MacroNewsItem(
            published_at=r["published_at"],
            source=r["source"],
            headline=r["headline"],
            sentiment=r["sentiment"],
            score=round(float(r["score"]), 4),
            summary=r.get("summary", ""),
        )
        for r in rows
    ]
    summary_rows = db.query_rows(_NEWS_SUMMARY_SQL)
    summary = {s["sentiment"]: s["cnt"] for s in summary_rows}
    return MacroNewsResponse(news=news, summary=summary)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/quant/data-sources", response_model=DataSourcesResponse)
def api_quant_data_sources(db=Depends(get_quant_db)):
    return _get_data_sources(db)


@router.get("/quant/factors", response_model=FactorsResponse)
def api_quant_factors(db=Depends(get_quant_db)):
    return _get_factors(db)


@router.get("/quant/factors/{name}", response_model=FactorDetailResponse)
def api_quant_factor_detail(name: str, db=Depends(get_quant_db)):
    return _get_factor_detail(name, db)


@router.get("/quant/ohlcv", response_model=TimeSeriesResponse)
def api_quant_ohlcv(
    pair: str,
    start: Annotated[str, Query(pattern=r"^\d{8}$")],
    end: Annotated[str, Query(pattern=r"^\d{8}$")],
    db=Depends(get_quant_db),
):
    return _get_ohlcv(db, pair, start, end)


@router.get("/quant/factor-zscore", response_model=TimeSeriesResponse)
def api_quant_factor_zscore(
    pair: str,
    factor: str,
    start: Annotated[str, Query(pattern=r"^\d{8}$")],
    end: Annotated[str, Query(pattern=r"^\d{8}$")],
    db=Depends(get_quant_db),
):
    return _get_factor_zscore(db, pair, factor, start, end)


@router.get("/quant/ic-rolling", response_model=TimeSeriesResponse)
def api_quant_ic_rolling(factor: str, db=Depends(get_quant_db)):
    return _get_ic_rolling(db, factor)


@router.get("/quant/factor-correlation", response_model=CorrelationMatrixResponse)
def api_quant_factor_correlation(db=Depends(get_quant_db)):
    return _get_factor_correlation(db)


@router.get("/quant/nav", response_model=TimeSeriesResponse)
def api_quant_nav(factor: str, db=Depends(get_quant_db)):
    return _get_nav(db, factor)


@router.get("/quant/trades", response_model=TradesResponse)
def api_quant_trades(pair: str, factor: str, db=Depends(get_quant_db)):
    return _get_trades(db, pair, factor)


@router.get("/quant/macro-indicators", response_model=MacroIndicatorsResponse)
def api_quant_macro_indicators(
    lang: str = Query("zh_CN", regex="^(zh_CN|en_US)$"),
    db=Depends(get_quant_db),
):
    resp = _get_macro_indicators(db)
    resp.indicators = translate_indicators([i.model_dump() for i in resp.indicators], lang)
    return resp


@router.get("/quant/macro-indicators/{series_id}", response_model=MacroIndicatorSeriesResponse)
def api_quant_macro_series(series_id: str, db=Depends(get_quant_db)):
    return _get_macro_series(db, series_id)


@router.get("/quant/macro-news", response_model=MacroNewsResponse)
def api_quant_macro_news(db=Depends(get_quant_db)):
    return _get_macro_news(db)


# ---------------------------------------------------------------------------
# Sync endpoints
# ---------------------------------------------------------------------------

_SYNC_STATUS_SQL = "SELECT source, status, last_sync, last_result, row_count FROM quant_raw.sync_status ORDER BY source"
_SYNC_LOGS_SQL = "SELECT id, source, status, records, message, started_at, finished_at FROM quant_raw.sync_log ORDER BY id DESC LIMIT 20"
_SYNC_RESET_SQL = "UPDATE quant_raw.sync_status SET status='idle', last_error=NULL WHERE source=%s"


@router.get("/quant/sync/status")
def api_sync_status(
    lang: str = Query("zh_CN", regex="^(zh_CN|en_US)$"),
    db=Depends(get_quant_db),
):
    """获取各数据源的同步状态"""
    db = _require_db(db)
    rows = db.query_rows(_SYNC_STATUS_SQL)
    return {"sources": translate_sync_status(rows, lang)}


@router.get("/quant/sync/logs")
def api_sync_logs(db=Depends(get_quant_db)):
    """获取同步执行日志（最近20条）"""
    db = _require_db(db)
    rows = db.query_rows(_SYNC_LOGS_SQL)
    return {"logs": rows}


@router.post("/quant/sync/news")
def api_sync_news(db=Depends(get_quant_db)):
    """触发新闻同步（后台执行，立即返回）"""
    import threading

    db = _require_db(db)
    db.query_rows("UPDATE quant_raw.sync_status SET status='running' WHERE source='news'")

    def _run():
        try:
            import os
            import subprocess
            import time

            from freqtrade.rpc.api_server.quant_db import QuantDB

            bg_db = QuantDB(
                "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"
            )
            start = time.time()
            script = os.path.expanduser(
                "~/work/trade/freqtrade/.worktrees/quant-mvp/user_data/scripts/sync_news_quick.py"
            )
            result = subprocess.run(
                ["/home/zp/work/trade/freqtrade/.venv/bin/python", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            elapsed = round(time.time() - start, 1)
            records = 0
            for l in result.stdout.strip().split("\n"):
                if "Written:" in l:
                    try:
                        import re

                        m = re.search(r"(\d+)", l.split("Written:")[-1])
                        if m:
                            records = int(m.group(1))
                    except:
                        pass
            success = result.returncode == 0
            bg_db.query_rows(
                "UPDATE quant_raw.sync_status SET status='idle', last_sync=NOW(), last_result=%s, row_count=%s WHERE source='news'",
                ("success" if success else "failed", records),
            )
            bg_db.query_rows(
                "INSERT INTO quant_raw.sync_log (source,status,records,duration_s,message) VALUES ('news',%s,%s,%s,%s)",
                (
                    "success" if success else "failed",
                    records,
                    elapsed,
                    result.stderr.strip()[:200] if not success else f"抓取完成，{records}条",
                ),
            )
        except Exception as e:
            bg_db = QuantDB(
                "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"
            )
            bg_db.query_rows(
                "UPDATE quant_raw.sync_status SET status='idle', last_result='failed', last_error=%s WHERE source='news'",
                (str(e),),
            )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"source": "news", "status": "running"}


@router.post("/quant/sync/macro")
def api_sync_macro(db=Depends(get_quant_db)):
    """触发宏观数据同步（后台执行，立即返回）使用 OpenBB"""
    import threading

    db = _require_db(db)
    db.query_rows("UPDATE quant_raw.sync_status SET status='running' WHERE source='macro'")

    def _run():
        from freqtrade.rpc.api_server.quant_db import QuantDB

        bg_db = QuantDB("host=localhost port=5433 dbname=warehouse user=postgres password=postgres")
        try:
            import json
            import os
            import subprocess
            import time

            start = time.time()
            env = os.environ.copy()
            settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
            if os.path.exists(settings_path):
                with open(settings_path) as f:
                    env["FRED_API_KEY"] = json.load(f).get("fred", {}).get("api_key", "")
            script = os.path.expanduser(
                "~/work/trade/freqtrade/.worktrees/quant-mvp/user_data/scripts/sync_openbb.py"
            )
            result = subprocess.run(
                ["/home/zp/work/trade/freqtrade/.venv/bin/python", script, "--provider", "fred"],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            elapsed = round(time.time() - start, 1)
            success = result.returncode == 0
            records = 0
            for l in result.stdout.strip().split("\n"):
                if "Total:" in l:
                    import re

                    m = re.search(r"(\d+)", l)
                    if m:
                        records = int(m.group(1))
            status_msg = (
                f"OpenBB FRED {records // 1000}k行" if success else result.stderr.strip()[:200]
            )
            bg_db.query_rows(
                "UPDATE quant_raw.sync_status SET status='idle', last_sync=NOW(), "
                "last_result=%s, row_count=%s WHERE source='macro'",
                ("success" if success else "failed", records),
            )
            bg_db.query_rows(
                "INSERT INTO quant_raw.sync_log (source,status,records,duration_s,message) "
                "VALUES ('macro',%s,%s,%s,%s)",
                ("success" if success else "failed", records, elapsed, status_msg),
            )
        except Exception as e:
            bg_db.query_rows(
                "UPDATE quant_raw.sync_status SET status='idle', last_result='failed', "
                "last_error=%s WHERE source='macro'",
                (str(e),),
            )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"source": "macro", "status": "running"}


@router.post("/quant/sync/crypto")
def api_sync_crypto(db=Depends(get_quant_db)):
    """触发数字货币数据同步（后台执行，立即返回）"""
    import threading

    db = _require_db(db)
    db.query_rows("UPDATE quant_raw.sync_status SET status='running' WHERE source='crypto'")

    def _run():
        from freqtrade.rpc.api_server.quant_db import QuantDB

        bg_db = QuantDB("host=localhost port=5433 dbname=warehouse user=postgres password=postgres")
        try:
            import os
            import subprocess
            import time

            start = time.time()
            worktree = os.path.expanduser("~/work/trade/freqtrade/.worktrees/quant-mvp")
            result = subprocess.run(
                [
                    "/home/zp/work/trade/freqtrade/.venv/bin/python",
                    "-m",
                    "freqtrade",
                    "download-data",
                    "--config",
                    f"{worktree}/user_data/config_crypto_mvp.json",
                    "--timeframes",
                    "1h",
                    "--days",
                    "7",
                    "--data-format-ohlcv",
                    "feather",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=worktree,
            )
            elapsed = round(time.time() - start, 1)
            success = result.returncode == 0
            if success:
                subprocess.run(
                    [
                        "/home/zp/work/trade/freqtrade/.venv/bin/python",
                        "-m",
                        "user_data.scripts.feather_to_pg",
                    ],
                    capture_output=True,
                    cwd=worktree,
                    timeout=120,
                )
            bg_db.query_rows(
                "UPDATE quant_raw.sync_status SET status='idle', last_sync=NOW(), "
                "last_result=%s, row_count=(SELECT COUNT(*) FROM quant_raw.ohlcv_crypto) "
                "WHERE source='crypto'",
                ("success" if success else "failed",),
            )
            bg_db.query_rows(
                "INSERT INTO quant_raw.sync_log (source,status,duration_s,message) "
                "VALUES ('crypto',%s,%s,%s)",
                (
                    "success" if success else "failed",
                    elapsed,
                    result.stderr.strip()[:200] if not success else "行情数据同步完成",
                ),
            )
        except Exception as e:
            bg_db.query_rows(
                "UPDATE quant_raw.sync_status SET status='idle', last_result='failed', "
                "last_error=%s WHERE source='crypto'",
                (str(e),),
            )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"source": "crypto", "status": "running"}


@router.post("/quant/sync/dbt")
def api_sync_dbt(db=Depends(get_quant_db)):
    """触发 dbt 模型运行"""
    db = _require_db(db)
    try:
        import os
        import subprocess
        import time

        start = time.time()
        env = os.environ.copy()
        env["QUANT_PG_HOST"] = "localhost"
        env["QUANT_PG_PORT"] = "5433"
        dbt_dir = os.path.expanduser("~/airbyte/quant_warehouse")
        result = subprocess.run(
            ["dbt", "run", "--profiles-dir", "."],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=dbt_dir,
            env=env,
        )
        elapsed = round(time.time() - start, 1)
        success = result.returncode == 0
        records = result.stdout.count("OK created") + result.stdout.count("PASS")
        db.query_rows(
            "INSERT INTO quant_raw.sync_log (source,status,records,duration_s,message) VALUES ('dbt',%s,%s,%s,%s)",
            (
                "success" if success else "failed",
                records,
                elapsed,
                result.stderr.strip()[:200] if not success else f"dbt {records}个模型通过",
            ),
        )
        return {
            "source": "dbt",
            "status": "success" if success else "failed",
            "records": records,
            "duration_s": elapsed,
        }
    except Exception as e:
        return {"source": "dbt", "status": "failed", "error": str(e)}


# ── AI 对话分析 v2 (P3: 动态MCP工具 + 自适应多轮 + SSE流式) ──────────

import re as _re
import urllib.request as _urllib


# Factor MCP Server 地址
_FACTOR_MCP_URL = "http://localhost:29010"

# 本地DB工具定义（不依赖MCP的固定工具）
_DB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_crypto_price",
            "description": "获取数字货币最新价格和OHLCV数据",
            "parameters": {
                "type": "object",
                "properties": {"pair": {"type": "string", "description": "交易对，如 BTC/USDT"}},
                "required": ["pair"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "获取最新加密货币相关新闻",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，默认5", "default": 5}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_macro_indicators",
            "description": "获取最新宏观经济指标值（CPI, Fed Rate, VIX, DXY, 10Y-2Y Spread等17个指标）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

_AI_SYSTEM_PROMPT = """你是一个加密货币量化分析助手 DeepSeek QuantTrader。你可以使用工具查询实时数据。

回答规则：
1. 优先使用工具获取最新数据，不要编造数字
2. 用中文回答，简洁专业。使用 Markdown 格式组织内容
3. 如果用户提到特定币对但没指定，默认使用 BTC/USDT
4. 分析时给出具体数值和方向判断（看多/看空/中性）
5. 结合宏观经济背景给出综合判断
6. 充分利用所有可用工具，可以做多步分析后再给出结论"""


def _discover_mcp_tools() -> list[dict]:
    """从 Factor MCP Server 动态发现工具，转换为 OpenAI function calling 格式."""
    try:
        req = _urllib.Request(f"{_FACTOR_MCP_URL}/tools")
        with _urllib.urlopen(req, timeout=3) as r:
            raw_tools = json.loads(r.read())
        tools = []
        for t in raw_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                }
            )
        return tools
    except Exception:
        return []


def _execute_tool(name: str, args: dict) -> str:
    """统一工具执行入口：MCP 工具 → HTTP调用；DB工具 → 本地执行."""
    # 优先通过 MCP 执行（因子相关工具）
    mcp_tools = {
        "get_factor_ranking",
        "get_factor_zscore",
        "get_factor_correlation",
        "get_composite_signal",
        "get_macro_indicators",
    }
    if name in mcp_tools:
        try:
            data = json.dumps(args).encode()
            req = _urllib.Request(
                f"{_FACTOR_MCP_URL}/call/{name}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _urllib.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
            text = "\n".join(result.get("result", []))
            # 截断过长结果
            return text[:3000]
        except Exception as e:
            return f"MCP调用失败({name}): {e}"

    # 本地 DB 工具
    dsn = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"
    if name == "get_crypto_price":
        pair = args.get("pair", "BTC/USDT")
        db = QuantDB(dsn)
        try:
            rows = db.query_rows(
                "SELECT pair, date, open, high, low, close, volume "
                "FROM quant_raw.ohlcv_crypto WHERE pair=%s ORDER BY date DESC LIMIT 5",
                (pair,),
            )
            if not rows:
                return f"未找到 {pair} 的价格数据"
            latest = rows[0]
            return (
                f"{pair} 最新价格:\n  时间: {latest['date']}\n"
                f"  开盘: {float(latest['open']):.2f}  最高: {float(latest['high']):.2f}\n"
                f"  最低: {float(latest['low']):.2f}  收盘: {float(latest['close']):.2f}\n"
                f"  成交量: {float(latest['volume']):.2f}"
            )
        finally:
            db.close()

    elif name == "get_news":
        limit = args.get("limit", 5)
        db = QuantDB(dsn)
        try:
            rows = db.query_rows(
                "SELECT headline, source, sentiment, published_at "
                "FROM quant_raw.news_sentiment ORDER BY published_at DESC LIMIT %s",
                (limit,),
            )
            if not rows:
                return "暂无新闻数据"
            emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}
            lines = ["最新加密货币新闻:"]
            for r in rows:
                e = emoji.get(r["sentiment"], "⚪")
                lines.append(f"  {e} [{r['source'][:20]}] {r['headline'][:80]}")
            return "\n".join(lines)
        finally:
            db.close()

    elif name == "get_macro_indicators":
        db = QuantDB(dsn)
        try:
            rows = db.query_rows(
                "SELECT DISTINCT ON (series_id) series_id, date, value "
                "FROM quant_raw.macro_indicators ORDER BY series_id, date DESC"
            )
            lines = ["最新宏观经济指标:"]
            for r in rows:
                d = str(r["date"])[:10] if r["date"] else "?"
                lines.append(f"  {r['series_id']}: {r['value']:.4f} (截至 {d})")
            return "\n".join(lines)
        finally:
            db.close()

    return f"未知工具: {name}"


def _resolve_deepseek_key() -> str:
    """从 Hermes 配置读取 DeepSeek API Key."""
    settings = os.path.expanduser("~/.hermes/config.yaml")
    if os.path.exists(settings):
        with open(settings) as f:
            cfg = yaml.safe_load(f)
        key = cfg.get("providers", {}).get("deepseek", {}).get("api_key")
        if key:
            return key
    raise RuntimeError("DeepSeek API key not configured")


# ── Skills 系统 (P4: 对标 Anthropic Fin SKILL.md 格式) ──────────

_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "user_data",
    "skills",
)


def _parse_skill_metadata(md_path: str) -> dict | None:
    """解析 SKILL.md 的 YAML frontmatter。"""
    try:
        with open(md_path) as f:
            content = f.read()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                meta = yaml.safe_load(parts[1])
                meta["_body"] = parts[2].strip()
                meta["_path"] = md_path
                return meta
    except Exception as e:
        logger.warning(f"Failed to parse skill {md_path}: {e}")
    return None


def _load_skill(name: str) -> dict | None:
    """加载指定 Skill 的完整元数据和内容。"""
    skill_dir = os.path.join(_SKILLS_DIR, name)
    md_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(md_path):
        return None
    meta = _parse_skill_metadata(md_path)
    if not meta:
        return None
    # 加载 references
    refs = []
    refs_dir = os.path.join(skill_dir, "references")
    if os.path.isdir(refs_dir):
        for fname in sorted(os.listdir(refs_dir)):
            if fname.endswith(".md") or fname.endswith(".json"):
                try:
                    with open(os.path.join(refs_dir, fname)) as f:
                        refs.append({"name": fname, "content": f.read()[:3000]})
                except Exception:
                    pass
    meta["references"] = refs
    return meta


def _list_skills() -> list[dict]:
    """列出所有可用 Skills。"""
    skills = []
    if not os.path.isdir(_SKILLS_DIR):
        return skills
    for name in sorted(os.listdir(_SKILLS_DIR)):
        if name.startswith("_") or name.startswith("."):
            continue
        meta = _load_skill(name)
        if meta:
            skills.append(
                {
                    "name": meta.get("name", name),
                    "description": meta.get("description", ""),
                    "version": meta.get("version", "1.0.0"),
                    "tags": meta.get("metadata", {}).get("tags", []),
                }
            )
    return skills


@router.get("/quant/skills")
def api_list_skills():
    """列出所有可用的量化分析 Skills。"""
    return {"skills": _list_skills()}


@router.get("/quant/skills/{name}")
def api_get_skill(name: str):
    """获取指定 Skill 的详情。"""
    skill = _load_skill(name)
    if not skill:
        raise HTTPException(404, f"Skill '{name}' not found")
    return {
        "name": skill.get("name"),
        "description": skill.get("description"),
        "version": skill.get("version"),
        "body": skill.get("_body", "")[:2000],
        "references": [r["name"] for r in skill.get("references", [])],
    }


@router.post("/quant/chat")
def api_quant_chat_v2(payload: dict, db=Depends(get_quant_db)):
    """AI 量化分析 v2 — 动态MCP工具 + 自适应多轮 + SSE流式 + Skills。
    接收: {"messages": [...], "pair": "BTC/USDT", "stream": true, "skill": "factor-deep-dive"}
    """
    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(400, "messages is required")

    api_key = _resolve_deepseek_key()
    user_pair = payload.get("pair", "BTC/USDT")
    stream = payload.get("stream", False)
    skill_name = payload.get("skill", "")

    # 动态发现 MCP 工具 + 合并固定DB工具（去重：MCP工具优先）
    mcp_tools = _discover_mcp_tools()
    mcp_names = {t["function"]["name"] for t in mcp_tools}
    db_filtered = [t for t in _DB_TOOLS if t["function"]["name"] not in mcp_names]
    all_tools = db_filtered + mcp_tools
    logger.info(
        f"AI chat: {len(db_filtered)} DB tools + {len(mcp_tools)} MCP tools = {len(all_tools)} total"
    )

    # 构建系统提示词：基础 + Skill 增强
    sys_parts = [_AI_SYSTEM_PROMPT]
    sys_parts.append(f"\n当前上下文: 用户关注 {user_pair}")
    sys_parts.append(f"可用工具: {', '.join(t['function']['name'] for t in all_tools)}")

    if skill_name:
        skill = _load_skill(skill_name)
        if skill:
            skill_body = skill.get("_body", "")
            skill_refs = skill.get("references", [])
            sys_parts.append(f"\n## 当前激活的 Skill: {skill_name}")
            sys_parts.append(skill_body[:3000])
            if skill_refs:
                sys_parts.append("\n### Skill References:")
                for ref in skill_refs[:5]:
                    sys_parts.append(f"\n--- {ref['name']} ---\n{ref['content'][:1500]}")
            sys_parts.append(f"\n请严格遵循以上 Skill 定义的分析流程和输出格式。")
            logger.info(f"Skill loaded: {skill_name}")
        else:
            logger.warning(f"Skill not found: {skill_name}")

    sys_msg = "\n\n".join(sys_parts)

    api_messages = [{"role": "system", "content": sys_msg}] + messages
    tool_calls_log = []

    def _call_llm(msgs, tools=None):
        body = {"model": "deepseek-chat", "messages": msgs, "temperature": 0.3, "max_tokens": 1024}
        if tools:
            body["tools"] = tools
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]

    def _stream_response(final_text: str, tool_log: list):
        """生成 SSE 事件流。"""
        # 首先发送工具调用事件
        for tc in tool_log:
            yield f"data: {json.dumps({'type': 'tool_call', 'tool': tc['tool'], 'args': tc['args'], 'result': tc['result'][:500]}, ensure_ascii=False)}\n\n"
        # 然后逐块发送最终回答
        chunk_size = 20
        for i in range(0, len(final_text), chunk_size):
            chunk = final_text[i : i + chunk_size]
            yield f"data: {json.dumps({'type': 'text', 'content': chunk}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    try:
        if stream:
            from fastapi.responses import StreamingResponse

            def generate():
                msgs = list(api_messages)
                log = []
                # 自适应多轮推理（最多5轮）
                for turn in range(5):
                    msg = _call_llm(msgs, all_tools)
                    if msg.get("tool_calls"):
                        msgs.append(msg)
                        for tc in msg["tool_calls"]:
                            fn = tc["function"]["name"]
                            args = json.loads(tc["function"]["arguments"])
                            result = _execute_tool(fn, args)
                            log.append({"tool": fn, "args": args, "result": result[:500]})
                            msgs.append(
                                {"role": "tool", "tool_call_id": tc["id"], "content": result}
                            )
                    else:
                        # 最终回答
                        final = msg.get("content", "")
                        yield from _stream_response(final, log)
                        return
                # 超过最大轮次，强制输出
                final = _call_llm(msgs, None).get("content", "分析超时，请简化问题重试")
                yield from _stream_response(final, log)

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
            )
        else:
            # 非流式模式（兼容旧前端）
            msgs = list(api_messages)
            for turn in range(5):
                msg = _call_llm(msgs, all_tools)
                if msg.get("tool_calls"):
                    msgs.append(msg)
                    for tc in msg["tool_calls"]:
                        fn = tc["function"]["name"]
                        args = json.loads(tc["function"]["arguments"])
                        result = _execute_tool(fn, args)
                        tool_calls_log.append({"tool": fn, "args": args, "result": result[:500]})
                        msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                else:
                    return {"response": msg.get("content", ""), "tool_calls": tool_calls_log}
            final = _call_llm(msgs, None).get("content", "分析超时")
            return {"response": final, "tool_calls": tool_calls_log}

    except Exception as e:
        logger.exception("AI chat error")
        raise HTTPException(500, f"AI 分析失败: {str(e)}")
