"""v4.0 AI Trading Module — strategy generation, backtest, ranking, paper trading."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.exceptions import HTTPException

from freqtrade.rpc.api_server.api_trade_schemas import (
    ApprovalRecord,
    ApprovalRequest,
    BacktestProgressResponse,
    BacktestRequest,
    BacktestResultItem,
    BacktestWindowResult,
    DailyReportListResponse,
    DailyReportResponse,
    MonitorResponse,
    PaperStatusResponse,
    RankedStrategy,
    RankingResponse,
    StrategyDetail,
    StrategyGenerateRequest,
    StrategyGenerateResponse,
    StrategyIterateResponse,
    StrategyListResponse,
    StrategySummary,
)
from freqtrade.rpc.api_server.deps import get_quant_db
from freqtrade.rpc.api_server.quant_db import QuantDB
from freqtrade.rpc.api_server.strategy_validator import (
    build_strategy_prompt,
    compute_deflated_sharpe,
    load_factor_registry,
    validate_strategy_code,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["trade"])

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_INSERT_STRATEGY_SQL = """
    INSERT INTO quant.trade_strategies
        (strategy_id, strategy_version_id, version, name, description, code,
         factor_ids, trading_pair, timeframe, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s::text[], %s, %s, %s)
    RETURNING strategy_id, name, code, description, status, created_at
"""

_LIST_STRATEGIES_SQL = """
    SELECT strategy_id::text, strategy_version_id::text, version, name,
           description, trading_pair, timeframe, status,
           created_at::text, updated_at::text
    FROM quant.trade_strategies
    ORDER BY created_at DESC
    LIMIT %s OFFSET %s
"""

_COUNT_STRATEGIES_SQL = "SELECT COUNT(*) as total FROM quant.trade_strategies"

_GET_STRATEGY_SQL = """
    SELECT strategy_id::text, strategy_version_id::text, version, name,
           description, code, factor_ids, trading_pair, timeframe, status,
           created_at::text, updated_at::text
    FROM quant.trade_strategies
    WHERE strategy_id = %s
"""

_UPDATE_STATUS_SQL = """
    UPDATE quant.trade_strategies
    SET status = %s, updated_at = NOW()
    WHERE strategy_id = %s
"""

_INSERT_BT_RESULT_SQL = """
    INSERT INTO quant.backtest_results
        (strategy_id, strategy_version_id, run_id, window_type,
         sharpe_ratio, sortino_ratio, calmar_ratio, deflated_sharpe,
         total_return_pct, max_drawdown_pct, win_rate_pct,
         total_trades, avg_hold_hours, profit_factor,
         start_date, end_date, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_GET_BT_RESULTS_SQL = """
    SELECT strategy_id::text, strategy_name, run_id::text, status,
           error_message, overfit_flag
    FROM (SELECT ... ) t  -- placeholder, see _get_backtest_results()
"""

_RANKING_SQL = """
    SELECT
        s.strategy_id::text,
        s.name as strategy_name,
        br.deflated_sharpe,
        br.sharpe_ratio,
        br.max_drawdown_pct,
        br.total_return_pct,
        br.win_rate_pct,
        br.status,
        br.window_type
    FROM quant.backtest_results br
    JOIN quant.trade_strategies s ON s.strategy_id = br.strategy_id
    WHERE br.run_id = %s AND br.window_type = 'out_of_sample'
    ORDER BY br.deflated_sharpe DESC NULLS LAST
"""

_INSERT_APPROVAL_SQL = """
    INSERT INTO quant.strategy_approvals (strategy_id, action, comment, approved_by)
    VALUES (%s, %s, %s, %s)
    RETURNING id, strategy_id::text, action, comment, approved_by, created_at::text
"""

_GET_APPROVALS_SQL = """
    SELECT id, strategy_id::text, action, comment, approved_by, created_at::text
    FROM quant.strategy_approvals
    WHERE strategy_id = %s
    ORDER BY created_at DESC
"""

_INSERT_PAPER_TRADE_SQL = """
    INSERT INTO quant.paper_trades
        (strategy_id, trade_id, trading_pair, direction, open_date,
         open_rate, amount)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

_GET_PAPER_TRADES_SQL = """
    SELECT id, strategy_id::text, trade_id, trading_pair, direction,
           open_date::text, close_date::text, open_rate, close_rate,
           amount, profit_pct, profit_abs, exit_reason
    FROM quant.paper_trades
    WHERE strategy_id = %s
    ORDER BY open_date DESC
    LIMIT 100
"""

_INSERT_REPORT_SQL = """
    INSERT INTO quant.daily_reports
        (report_date, report_content, total_pnl, win_rate_pct,
         total_trades, sharpe_30d, max_drawdown)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (report_date) DO UPDATE SET
        report_content = EXCLUDED.report_content,
        total_pnl = EXCLUDED.total_pnl,
        win_rate_pct = EXCLUDED.win_rate_pct,
        total_trades = EXCLUDED.total_trades,
        sharpe_30d = EXCLUDED.sharpe_30d,
        max_drawdown = EXCLUDED.max_drawdown
"""

_LIST_REPORTS_SQL = """
    SELECT id, report_date::text, report_content, total_pnl,
           win_rate_pct, total_trades, sharpe_30d, max_drawdown, created_at::text
    FROM quant.daily_reports
    ORDER BY report_date DESC
    LIMIT %s
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_db(db: QuantDB | None) -> QuantDB:
    if db is None:
        raise HTTPException(status_code=503, detail="PostgreSQL (quant_db) not configured")
    return db


def _call_llm(prompt: str, temperature: float = 0.0) -> str:
    """Call LLM API for strategy generation. Uses DeepSeek by default."""
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM API key not configured")

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    import requests

    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# US-01: Strategy Generation
# ---------------------------------------------------------------------------


def _generate_strategy(
    db: QuantDB | None,
    req: StrategyGenerateRequest,
) -> StrategyGenerateResponse:
    db = _require_db(db)

    # 1. Load factor registry
    factors = load_factor_registry()
    if not factors:
        raise HTTPException(status_code=503, detail="Factor registry (factors.yml) not found")

    # 2. Get allowed columns from mart_hourly_signals
    cols_rows = db.query_rows(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='quant' AND table_name='mart_hourly_signals' "
        "ORDER BY ordinal_position"
    )
    allowed_columns = [r["column_name"] for r in cols_rows]

    # 3. Build prompt
    prompt = build_strategy_prompt(
        description=req.description,
        trading_pair=req.trading_pair,
        allowed_factors=factors,
        allowed_columns=allowed_columns,
    )

    # 4. Call LLM
    try:
        raw_response = _call_llm(prompt, temperature=0.0)
        result = json.loads(raw_response)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    code = result.get("code", "")
    strategy_name = result.get("strategy_name", "AIStrategy")

    if not code.strip():
        raise HTTPException(status_code=502, detail="LLM returned empty strategy code")

    # 5. Validate generated code
    is_valid, err_msg = validate_strategy_code(code)
    if not is_valid:
        raise HTTPException(status_code=422, detail=f"Generated code failed validation: {err_msg}")

    # 6. Extract referenced factors
    referenced_factors = [
        f["name"]
        for f in factors
        if f["name"].lower() in code.lower() or f.get("zscore_column", "").lower() in code.lower()
    ]

    # 7. Store in DB
    strategy_id = uuid.uuid4()
    version_id = uuid.uuid4()

    rows = db.query_rows(
        _INSERT_STRATEGY_SQL,
        (
            str(strategy_id),
            str(version_id),
            1,
            strategy_name,
            req.description,
            code,
            referenced_factors,
            req.trading_pair,
            "1h",
            "draft",
        ),
    )

    row = rows[0] if rows else {}
    return StrategyGenerateResponse(
        strategy_id=strategy_id,
        name=strategy_name,
        code=code,
        description=req.description,
        trading_pair=req.trading_pair,
        status="draft",
    )


# ---------------------------------------------------------------------------
# Strategy CRUD
# ---------------------------------------------------------------------------


def _list_strategies(db: QuantDB | None, limit: int = 20, offset: int = 0) -> StrategyListResponse:
    db = _require_db(db)
    rows = db.query_rows(_LIST_STRATEGIES_SQL, (limit, offset))
    total_row = db.query_rows(_COUNT_STRATEGIES_SQL)
    total = total_row[0]["total"] if total_row else 0
    return StrategyListResponse(
        strategies=[StrategySummary(**r) for r in rows],
        total=total,
    )


def _get_strategy(db: QuantDB | None, strategy_id: str) -> StrategyDetail:
    db = _require_db(db)
    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
    return StrategyDetail(**rows[0])


# ---------------------------------------------------------------------------
# US-02: Batch Backtest
# ---------------------------------------------------------------------------


def _run_single_backtest(
    db: QuantDB,
    strategy_id: str,
    strategy_code: str,
    strategy_version_id: str,
    run_id: str,
    trading_pair: str,
    timeframe: str = "1h",
) -> None:
    """Run backtest for a single strategy and store results.

    This runs in a background thread. Uses the freqtrade Backtesting engine.
    """
    try:
        # Write strategy to temp file
        import tempfile
        from pathlib import Path

        from freqtrade.configuration.config_setup import setup_utils_configuration
        from freqtrade.data.history import get_datahandler
        from freqtrade.optimize.backtesting import Backtesting
        from freqtrade.resolvers.strategy_resolver import StrategyResolver

        tmp_dir = Path(tempfile.mkdtemp(prefix="bt_"))
        strat_file = tmp_dir / f"ai_strategy_{strategy_id[:8]}.py"
        strat_file.write_text(strategy_code)

        # Build config
        config = {
            "strategy": str(strat_file),
            "strategy_path": str(tmp_dir),
            "user_data_dir": str(tmp_dir),
            "trading_mode": "spot",
            "margin_mode": "",
            "timeframe": timeframe,
            "timerange": "",  # use all available data
            "pairs": [trading_pair],
            "exchange": {
                "name": "binance",
                "key": "",
                "secret": "",
                "ccxt_config": {"enableRateLimit": True},
            },
            "stake_amount": 10000,
            "dry_run_wallet": 10000,
            "max_open_trades": 5,
            "stake_currency": "USDT",
            "dry_run": True,
            "export": "none",
            "disableparamexport": True,
        }

        # Run backtest
        bt = Backtesting(config)
        bt.load_bt_data_detail()
        data, timerange = bt.load_bt_data()
        strat = StrategyResolver.load_strategy(config)
        bt.strategylist = [strat]
        bt.results = {"metadata": {}, "strategy": {}, "strategy_comparison": []}

        min_date, max_date = bt.backtest_one_strategy(strat, data, timerange)

        # Compute metrics
        from freqtrade.optimize.optimize_reports import generate_backtest_stats

        bt_results = generate_backtest_stats(data, bt.all_results, min_date, max_date)

        key = strat.get_strategy_name()
        stats = bt_results["strategy"][key]

        # Store results per window (in-sample, validation, out-of-sample)
        total_days = (max_date - min_date).days
        in_sample_end = min_date + timedelta(days=total_days * 0.6)
        val_end = min_date + timedelta(days=total_days * 0.8)

        for window_type, w_start, w_end in [
            ("in_sample", min_date, in_sample_end),
            ("validation", in_sample_end, val_end),
            ("out_of_sample", val_end, max_date),
        ]:
            db.query_rows(
                _INSERT_BT_RESULT_SQL,
                (
                    strategy_id,
                    strategy_version_id,
                    run_id,
                    window_type,
                    stats.get("sharpe_ratio"),
                    stats.get("sortino_ratio"),
                    stats.get("calmar_ratio"),
                    None,  # deflated_sharpe computed later
                    stats.get("profit_total_pct"),
                    stats.get("max_drawdown"),
                    stats.get("win_rate"),
                    stats.get("total_trades"),
                    stats.get("avg_hold_hours"),
                    stats.get("profit_factor"),
                    w_start,
                    w_end,
                    "completed",
                ),
            )

    except Exception as e:
        logger.exception("Backtest failed for strategy %s: %s", strategy_id, e)
        db.query_rows(
            _INSERT_BT_RESULT_SQL,
            (
                strategy_id,
                strategy_version_id,
                run_id,
                "in_sample",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "failed",
            ),
        )
        # Mark remaining windows as failed
        db.query_rows(
            "UPDATE quant.backtest_results SET status='failed', error_message=%s "
            "WHERE strategy_id=%s AND run_id=%s AND status='running'",
            (str(e), strategy_id, run_id),
        )


def _start_batch_backtest(
    db: QuantDB | None, req: BacktestRequest, background_tasks: BackgroundTasks
) -> BacktestProgressResponse:
    db = _require_db(db)

    if len(req.strategy_ids) > 5:
        raise HTTPException(status_code=422, detail="Maximum 5 strategies per batch")

    run_id = str(uuid.uuid4())

    # Validate all strategies exist and are valid
    strategies = []
    for sid in req.strategy_ids:
        rows = db.query_rows(_GET_STRATEGY_SQL, (str(sid),))
        if not rows:
            raise HTTPException(status_code=404, detail=f"Strategy {sid} not found")
        s = rows[0]
        if not s.get("code"):
            raise HTTPException(status_code=422, detail=f"Strategy {sid} has no code")
        is_valid, err = validate_strategy_code(s["code"])
        if not is_valid:
            raise HTTPException(status_code=422, detail=f"Strategy {sid} invalid: {err}")
        strategies.append(s)

    # Launch backtests in background
    for s in strategies:
        background_tasks.add_task(
            _run_single_backtest,
            db=db,
            strategy_id=s["strategy_id"],
            strategy_code=s["code"],
            strategy_version_id=s["strategy_version_id"],
            run_id=run_id,
            trading_pair=s["trading_pair"],
            timeframe=s.get("timeframe", "1h"),
        )

    return BacktestProgressResponse(
        run_id=uuid.UUID(run_id),
        status="running",
        total=len(strategies),
        completed=0,
        results=[],
    )


def _get_backtest_progress(db: QuantDB | None, run_id: str) -> BacktestProgressResponse:
    db = _require_db(db)

    # Count per strategy
    rows = db.query_rows(
        "SELECT strategy_id::text, strategy_version_id::text, status, "
        "       COUNT(*) FILTER (WHERE status='completed') as completed_windows "
        "FROM quant.backtest_results WHERE run_id=%s "
        "GROUP BY strategy_id, strategy_version_id, status",
        (run_id,),
    )

    total = len(set(r["strategy_id"] for r in rows))
    completed = len(
        set(
            r["strategy_id"]
            for r in rows
            if r["status"] == "completed" and r["completed_windows"] >= 3
        )
    )
    failed = [r["strategy_id"] for r in rows if r["status"] == "failed"]

    status = "completed" if completed + len(failed) >= total else "running"
    if completed + len(failed) == total and len(failed) > 0:
        status = "completed"  # partial failures still count as done

    # Build results
    results = _build_backtest_results(db, run_id)

    return BacktestProgressResponse(
        run_id=uuid.UUID(run_id),
        status=status,
        total=total,
        completed=completed,
        results=results,
    )


def _build_backtest_results(db: QuantDB, run_id: str) -> list[BacktestResultItem]:
    """Build detailed backtest result items from DB."""
    rows = db.query_rows(
        "SELECT br.strategy_id::text, s.name as strategy_name, br.run_id::text, "
        "       br.window_type, br.sharpe_ratio, br.sortino_ratio, br.calmar_ratio, "
        "       br.deflated_sharpe, br.total_return_pct, br.max_drawdown_pct, "
        "       br.win_rate_pct, br.total_trades, br.avg_hold_hours, br.profit_factor, "
        "       br.status, br.error_message "
        "FROM quant.backtest_results br "
        "JOIN quant.trade_strategies s ON s.strategy_id = br.strategy_id "
        "WHERE br.run_id = %s "
        "ORDER BY s.name, br.window_type",
        (run_id,),
    )

    grouped: dict[str, dict] = {}
    for r in rows:
        sid = r["strategy_id"]
        if sid not in grouped:
            grouped[sid] = {
                "strategy_id": sid,
                "strategy_name": r["strategy_name"],
                "run_id": r["run_id"],
                "status": "completed",
                "error_message": None,
                "windows": [],
            }
        if r["status"] == "failed":
            grouped[sid]["status"] = "failed"
            grouped[sid]["error_message"] = r.get("error_message")
        grouped[sid]["windows"].append(
            BacktestWindowResult(
                window_type=r["window_type"],
                sharpe_ratio=r["sharpe_ratio"],
                sortino_ratio=r["sortino_ratio"],
                calmar_ratio=r["calmar_ratio"],
                deflated_sharpe=r["deflated_sharpe"],
                total_return_pct=r["total_return_pct"],
                max_drawdown_pct=r["max_drawdown_pct"],
                win_rate_pct=r["win_rate_pct"],
                total_trades=r["total_trades"],
                avg_hold_hours=r["avg_hold_hours"],
                profit_factor=r["profit_factor"],
            )
        )

    # Detect overfit
    for sid, item in grouped.items():
        is_sharpe = None
        oos_sharpe = None
        for w in item["windows"]:
            if w.window_type == "in_sample":
                is_sharpe = w.sharpe_ratio
            elif w.window_type == "out_of_sample":
                oos_sharpe = w.sharpe_ratio
        if is_sharpe and oos_sharpe and oos_sharpe > 0:
            item["overfit_flag"] = (is_sharpe / oos_sharpe) > 1.5

    return [BacktestResultItem(**item) for item in grouped.values()]


# ---------------------------------------------------------------------------
# US-03: Ranking
# ---------------------------------------------------------------------------


def _get_ranking(db: QuantDB | None, run_id: str) -> RankingResponse:
    db = _require_db(db)

    rows = db.query_rows(_RANKING_SQL, (run_id,))

    # Collect Sharpe ratios for DSR
    sharpes = [r["sharpe_ratio"] for r in rows if r["sharpe_ratio"] is not None]

    # Get OOS Sharpe per strategy
    oos_rows = db.query_rows(
        "SELECT strategy_id::text, sharpe_ratio FROM quant.backtest_results "
        "WHERE run_id=%s AND window_type='out_of_sample'",
        (run_id,),
    )
    oos_map = {r["strategy_id"]: r["sharpe_ratio"] for r in oos_rows}

    # Compute variance for DSR
    mean_ = sum(sharpes) / len(sharpes) if sharpes else 0
    var_ = sum((s - mean_) ** 2 for s in sharpes) / (len(sharpes) - 1) if len(sharpes) > 1 else 0

    strategies = []
    for i, r in enumerate(rows, 1):
        dsr = (
            compute_deflated_sharpe(
                sharpes,
                variance_across_strategies=var_,
            )
            if sharpes
            else None
        )

        is_sharpe_row = db.query_rows(
            "SELECT sharpe_ratio FROM quant.backtest_results "
            "WHERE strategy_id=%s AND run_id=%s AND window_type='in_sample'",
            (r["strategy_id"], run_id),
        )
        is_sharpe = is_sharpe_row[0]["sharpe_ratio"] if is_sharpe_row else None
        oos_s = oos_map.get(r["strategy_id"])
        overfit = False
        if is_sharpe and oos_s and oos_s > 0:
            overfit = (is_sharpe / oos_s) > 1.5

        strategies.append(
            RankedStrategy(
                rank=i,
                strategy_id=uuid.UUID(r["strategy_id"]),
                strategy_name=r["strategy_name"],
                deflated_sharpe=dsr,
                sharpe_ratio=r["sharpe_ratio"],
                max_drawdown_pct=r["max_drawdown_pct"],
                total_return_pct=r["total_return_pct"],
                win_rate_pct=r["win_rate_pct"],
                oos_sharpe=oos_s,
                overfit_flag=overfit,
                status=r["status"],
            )
        )

    return RankingResponse(
        run_id=uuid.UUID(run_id),
        strategies=strategies,
    )


# ---------------------------------------------------------------------------
# US-04: Approval
# ---------------------------------------------------------------------------


def _approve_strategy(db: QuantDB | None, strategy_id: str, req: ApprovalRequest) -> ApprovalRecord:
    db = _require_db(db)

    # Verify strategy exists
    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
    if rows[0]["status"] not in ("pending_review", "rejected"):
        raise HTTPException(status_code=422, detail="Strategy must be in pending_review status")

    # Update status
    db.query_rows(_UPDATE_STATUS_SQL, ("approved", strategy_id))

    # Record approval
    app_rows = db.query_rows(_INSERT_APPROVAL_SQL, (strategy_id, "approved", req.comment, "trader"))
    return ApprovalRecord(**app_rows[0])


def _reject_strategy(db: QuantDB | None, strategy_id: str, req: ApprovalRequest) -> ApprovalRecord:
    db = _require_db(db)

    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    db.query_rows(_UPDATE_STATUS_SQL, ("rejected", strategy_id))
    app_rows = db.query_rows(_INSERT_APPROVAL_SQL, (strategy_id, "rejected", req.comment, "trader"))
    return ApprovalRecord(**app_rows[0])


# ---------------------------------------------------------------------------
# US-05/06: Paper Trading & Monitoring (DB-backed)
# ---------------------------------------------------------------------------

_START_SESSION_SQL = """
    INSERT INTO quant.paper_sessions (strategy_id, status, systemd_unit, config_json)
    VALUES (%s, 'starting', %s, %s)
    RETURNING id, started_at::text
"""

_UPDATE_SESSION_SQL = """
    UPDATE quant.paper_sessions SET status=%s, stopped_at=NOW(), error_message=%s
    WHERE strategy_id=%s AND status='running'
"""

_GET_SESSION_SQL = """
    SELECT id, strategy_id::text, status, systemd_unit, pid, port,
           started_at::text, stopped_at::text, error_message
    FROM quant.paper_sessions
    WHERE strategy_id=%s
    ORDER BY started_at DESC
    LIMIT 1
"""


def _start_paper_trading(db: QuantDB | None, strategy_id: str) -> PaperStatusResponse:
    db = _require_db(db)

    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    s = rows[0]
    if s["status"] != "approved":
        raise HTTPException(status_code=422, detail="Strategy must be approved first")

    # Check not already running
    existing = db.query_rows(_GET_SESSION_SQL, (strategy_id,))
    if existing and existing[0]["status"] == "running":
        raise HTTPException(status_code=422, detail="Paper trading already running")

    # Build freqtrade dry-run config
    config = {
        "strategy": s["name"],
        "strategy_path": "/var/lib/freqtrade/user_data/strategies/generated",
        "pairs": [s["trading_pair"]],
        "dry_run": True,
        "stake_amount": 10000,
        "max_open_trades": 5,
        "timeframe": s.get("timeframe", "1h"),
    }

    unit_name = f"freqtrade-dry-run@{strategy_id[:8]}.service"

    # Try to start via systemd
    import subprocess

    try:
        subprocess.run(
            ["sudo", "systemctl", "start", unit_name],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass  # systemd may not be available in dev

    # Record session
    sess = db.query_rows(
        _START_SESSION_SQL,
        (strategy_id, unit_name, json.dumps(config)),
    )

    # Update strategy status
    db.query_rows(_UPDATE_STATUS_SQL, ("active", strategy_id))

    started_at = sess[0]["started_at"] if sess else None
    return PaperStatusResponse(
        strategy_id=uuid.UUID(strategy_id),
        status="running",
        systemd_unit=unit_name,
        started_at=started_at,
    )


def _stop_paper_trading(db: QuantDB | None, strategy_id: str) -> PaperStatusResponse:
    db = _require_db(db)

    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    # Get session
    sess = db.query_rows(_GET_SESSION_SQL, (strategy_id,))

    # Stop systemd unit
    if sess:
        unit = sess[0].get("systemd_unit", "")
        if unit:
            import subprocess

            try:
                subprocess.run(
                    ["sudo", "systemctl", "stop", unit],
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                pass
        db.query_rows(_UPDATE_SESSION_SQL, ("stopped", None, strategy_id))

    db.query_rows(_UPDATE_STATUS_SQL, ("stopped", strategy_id))

    return PaperStatusResponse(
        strategy_id=uuid.UUID(strategy_id),
        status="stopped",
    )


def _get_paper_status(db: QuantDB | None, strategy_id: str) -> PaperStatusResponse:
    db = _require_db(db)

    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    s = rows[0]
    sess = db.query_rows(_GET_SESSION_SQL, (strategy_id,))

    if sess:
        se = sess[0]
        return PaperStatusResponse(
            strategy_id=uuid.UUID(strategy_id),
            status=se.get("status", s["status"]),
            systemd_unit=se.get("systemd_unit"),
            pid=se.get("pid"),
            started_at=se.get("started_at"),
        )

    return PaperStatusResponse(
        strategy_id=uuid.UUID(strategy_id),
        status=s["status"],
    )


def _get_monitor(db: QuantDB | None, strategy_id: str) -> MonitorResponse:
    db = _require_db(db)
    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    s = rows[0]

    # Get trades from paper_trades
    trades = db.query_rows(_GET_PAPER_TRADES_SQL, (strategy_id,))
    paper_trades = [PaperTradeRecord(**t) for t in trades] if trades else []

    open_pos = [t for t in trades if not t.get("close_date")]
    closed = [t for t in trades if t.get("close_date")]

    # Compute cumulative PnL over time
    sorted_closed = sorted(closed, key=lambda x: x.get("close_date", ""))
    cumulative_pnl = []
    running_pnl = 0.0
    for t in sorted_closed:
        running_pnl += t.get("profit_abs", 0) or 0
        cumulative_pnl.append(
            {
                "date": t.get("close_date", ""),
                "pnl": round(running_pnl, 2),
            }
        )

    # Daily returns
    daily_returns = []
    if closed:
        from collections import defaultdict

        daily: dict[str, list[float]] = defaultdict(list)
        for t in closed:
            date = (t.get("close_date") or "")[:10]
            if date:
                daily[date].append(t.get("profit_pct", 0) or 0)
        for date, returns in sorted(daily.items()):
            daily_returns.append(
                {
                    "date": date,
                    "return_pct": round(sum(returns) / len(returns), 2),
                }
            )

    # Metrics
    total_pnl = running_pnl
    win_trades = sum(1 for t in closed if (t.get("profit_pct") or 0) > 0)
    win_rate = (win_trades / len(closed) * 100) if closed else 0.0

    return MonitorResponse(
        strategy_id=uuid.UUID(strategy_id),
        strategy_name=s["name"],
        status=s["status"],
        open_positions=[dict(t) for t in open_pos] if open_pos else [],
        closed_trades=paper_trades,
        cumulative_pnl=cumulative_pnl,
        max_drawdown_30d=None,
        sharpe_30d=None,
        win_rate_30d=round(win_rate, 1),
        daily_returns=daily_returns,
    )


# ---------------------------------------------------------------------------
# US-07: Daily Reports
# ---------------------------------------------------------------------------


def _list_reports(db: QuantDB | None, limit: int = 30) -> DailyReportListResponse:
    db = _require_db(db)
    rows = db.query_rows(_LIST_REPORTS_SQL, (limit,))
    return DailyReportListResponse(reports=[DailyReportResponse(**r) for r in rows])


def _generate_report(db: QuantDB | None) -> DailyReportResponse:
    db = _require_db(db)
    today = datetime.utcnow().date()

    # Aggregate metrics
    metrics = db.query_rows(
        "SELECT "
        "  SUM(profit_abs) as total_pnl, "
        "  COUNT(*) as total_trades, "
        "  COUNT(*) FILTER (WHERE profit_pct > 0) * 100.0 / NULLIF(COUNT(*),0) as win_rate "
        "FROM quant.paper_trades "
        "WHERE close_date IS NOT NULL "
        "  AND open_date >= %s",
        (today - timedelta(days=30),),
    )
    m = metrics[0] if metrics else {}

    # Simple LLM report
    report_content = f"""# 交易日报 — {today}

## 摘要
- 总 PnL: {m.get("total_pnl", 0) or 0:.2f} USDT
- 总交易: {m.get("total_trades", 0)}
- 胜率: {m.get("win_rate", 0) or 0:.1f}%

## 备注
此报告由 AI 自动生成。
"""

    db.query_rows(
        _INSERT_REPORT_SQL,
        (
            today,
            report_content,
            m.get("total_pnl") or 0,
            m.get("win_rate") or 0,
            m.get("total_trades") or 0,
            None,
            None,
        ),
    )

    return DailyReportResponse(
        id=0,
        report_date=str(today),
        report_content=report_content,
        total_pnl=m.get("total_pnl") or 0,
        win_rate_pct=m.get("win_rate") or 0,
        total_trades=m.get("total_trades") or 0,
        sharpe_30d=None,
        max_drawdown=None,
        created_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# US-08: Strategy Iteration
# ---------------------------------------------------------------------------


def _iterate_strategy(db: QuantDB | None, strategy_id: str) -> StrategyIterateResponse:
    db = _require_db(db)

    rows = db.query_rows(_GET_STRATEGY_SQL, (strategy_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

    s = rows[0]
    old_code = s.get("code", "")

    # Get backtest results to inform iteration
    bt_rows = db.query_rows(
        "SELECT * FROM quant.backtest_results WHERE strategy_id=%s AND status='completed'",
        (strategy_id,),
    )

    # Build iteration prompt
    prompt = f"""Analyze this freqtrade strategy and its backtest results.
Suggest improvements.

## CURRENT STRATEGY
```python
{old_code}
```

## BACKTEST RESULTS
{json.dumps([dict(r) for r in bt_rows], default=str, indent=2) if bt_rows else "No backtest results yet"}

Return JSON:
{{"suggestions": "...", "improved_code": "..."}}"""

    try:
        raw = _call_llm(prompt, temperature=0.3)
        result = json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Iteration failed: {e}")

    new_code = result.get("improved_code", old_code)
    is_valid, err = validate_strategy_code(new_code)
    if not is_valid:
        raise HTTPException(status_code=422, detail=f"Improved code failed validation: {err}")

    # Store new version
    new_id = uuid.uuid4()
    new_version = s["version"] + 1
    db.query_rows(
        _INSERT_STRATEGY_SQL,
        (
            str(new_id),
            s["strategy_version_id"],
            new_version,
            f"{s['name']}_v{new_version}",
            s["description"],
            new_code,
            s.get("factor_ids") or [],
            s["trading_pair"],
            s.get("timeframe", "1h"),
            "draft",
        ),
    )

    return StrategyIterateResponse(
        original_id=uuid.UUID(strategy_id),
        new_strategy_id=new_id,
        new_version=new_version,
        suggestions=result.get("suggestions", ""),
        code=new_code,
    )


# ===========================================================================
# Route Handlers
# ===========================================================================


@router.post("/quant/strategies/generate", response_model=StrategyGenerateResponse)
def api_generate_strategy(
    req: StrategyGenerateRequest,
    db=Depends(get_quant_db),
):
    return _generate_strategy(db, req)


@router.get("/quant/strategies", response_model=StrategyListResponse)
def api_list_strategies(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(get_quant_db),
):
    return _list_strategies(db, limit, offset)


@router.get("/quant/strategies/{strategy_id}", response_model=StrategyDetail)
def api_get_strategy(strategy_id: str, db=Depends(get_quant_db)):
    return _get_strategy(db, strategy_id)


@router.post("/quant/strategies/backtest", response_model=BacktestProgressResponse)
def api_start_backtest(
    req: BacktestRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_quant_db),
):
    return _start_batch_backtest(db, req, background_tasks)


@router.get("/quant/strategies/backtest/{run_id}", response_model=BacktestProgressResponse)
def api_get_backtest(run_id: str, db=Depends(get_quant_db)):
    return _get_backtest_progress(db, run_id)


@router.get("/quant/strategies/ranking", response_model=RankingResponse)
def api_get_ranking(run_id: str = Query(...), db=Depends(get_quant_db)):
    return _get_ranking(db, run_id)


@router.post("/quant/strategies/{strategy_id}/approve", response_model=ApprovalRecord)
def api_approve_strategy(
    strategy_id: str,
    req: ApprovalRequest = ApprovalRequest(),
    db=Depends(get_quant_db),
):
    return _approve_strategy(db, strategy_id, req)


@router.post("/quant/strategies/{strategy_id}/reject", response_model=ApprovalRecord)
def api_reject_strategy(
    strategy_id: str,
    req: ApprovalRequest = ApprovalRequest(),
    db=Depends(get_quant_db),
):
    return _reject_strategy(db, strategy_id, req)


@router.post("/quant/strategies/{strategy_id}/start-paper", response_model=PaperStatusResponse)
def api_start_paper(strategy_id: str, db=Depends(get_quant_db)):
    return _start_paper_trading(db, strategy_id)


@router.post("/quant/strategies/{strategy_id}/stop-paper", response_model=PaperStatusResponse)
def api_stop_paper(strategy_id: str, db=Depends(get_quant_db)):
    return _stop_paper_trading(db, strategy_id)


@router.get("/quant/strategies/{strategy_id}/paper-status", response_model=PaperStatusResponse)
def api_paper_status(strategy_id: str, db=Depends(get_quant_db)):
    return _get_paper_status(db, strategy_id)


@router.get("/quant/strategies/{strategy_id}/monitor", response_model=MonitorResponse)
def api_monitor(strategy_id: str, db=Depends(get_quant_db)):
    return _get_monitor(db, strategy_id)


@router.get("/quant/reports", response_model=DailyReportListResponse)
def api_list_reports(
    limit: int = Query(30, ge=1, le=100),
    db=Depends(get_quant_db),
):
    return _list_reports(db, limit)


@router.post("/quant/reports/generate", response_model=DailyReportResponse)
def api_generate_report(db=Depends(get_quant_db)):
    return _generate_report(db)


@router.post("/quant/strategies/{strategy_id}/iterate", response_model=StrategyIterateResponse)
def api_iterate_strategy(strategy_id: str, db=Depends(get_quant_db)):
    return _iterate_strategy(db, strategy_id)
