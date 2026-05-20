"""Run a single-factor freqtrade backtest and return summary metrics."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


# Import parse_backtest from the existing script
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from backtest_to_pg import write_nav_rows  # noqa: E402


FREQTRADE_BIN = Path("/home/zp/work/trade/freqtrade/.venv/bin/freqtrade")
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config_crypto_mvp.json"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "backtest_results"


def _find_result_file(prefix: str) -> Path | None:
    """Find the latest backtest result file matching prefix (zip or json)."""
    # freqtrade appends timestamps to filenames, so we glob for the prefix
    candidates: list[str] = []
    for suffix in ("*.json", "*.zip"):
        candidates.extend(
            str(f)
            for f in RESULTS_DIR.glob(f"{prefix}{suffix}")
            if not str(f).endswith(".meta.json")
        )
    if not candidates:
        return None
    # Return the most recently modified
    return Path(max(candidates, key=os.path.getmtime))


def _load_backtest_json(path: Path) -> dict[str, Any]:
    """Load backtest result from either .json or .zip file."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            json_names = [n for n in zf.namelist() if n.endswith(".json")]
            if not json_names:
                raise ValueError(f"No JSON found in {path}")
            return json.loads(zf.read(json_names[0]))
    else:
        with path.open() as f:
            return json.load(f)


def _extract_summary(data: dict, run_id: str) -> tuple[list[tuple], dict]:
    """Extract NAV rows and summary from backtest JSON data."""
    strategies = data["strategy"]
    strategy_name = next(iter(strategies))
    s = strategies[strategy_name]

    daily_profit = s.get("daily_profit") or []
    starting_balance = float(s["starting_balance"])
    sharpe = float(s.get("sharpe") or 0.0)
    max_drawdown = float(s.get("max_drawdown_account") or 0.0)
    total_profit_pct = float(s.get("profit_total") or 0.0) * 100.0

    rows: list[tuple] = []
    nav = starting_balance
    for entry in daily_profit:
        date_str, profit = entry[0], float(entry[1])
        nav += profit
        rows.append((run_id, date_str, nav, sharpe, max_drawdown, total_profit_pct))

    summary = {
        "strategy_name": strategy_name,
        "starting_balance": starting_balance,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "total_profit_pct": total_profit_pct,
        "n_rows": len(rows),
    }
    return rows, summary


def run_one(
    factor_name: str,
    run_date: str,
    timerange: str = "20250411-20260410",
    config_path: Path = DEFAULT_CONFIG,
    dsn: str | None = None,
) -> dict:
    """Run backtest for a single factor. Returns summary dict with sharpe, max_dd, etc."""
    run_id = f"sprint2_{factor_name}_{run_date}"
    result_prefix = f"{run_id}"

    env = {**os.environ, "QUANT_FACTOR_NAME": factor_name}

    cmd = [
        str(FREQTRADE_BIN),
        "backtesting",
        "--config",
        str(config_path),
        "--strategy",
        "FactorSignalStrategy",
        "--timerange",
        timerange,
        "--export",
        "trades",
        "--export-filename",
        str(RESULTS_DIR / f"{result_prefix}.json"),
    ]

    log_dir = Path(tempfile.gettempdir()) / "sprint2_runs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{factor_name}.log"

    with log_path.open("w") as log_f:
        proc = subprocess.run(
            cmd,
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            timeout=120,
        )

    if proc.returncode != 0:
        return {
            "factor_name": factor_name,
            "run_id": run_id,
            "success": False,
            "error": f"freqtrade exit code {proc.returncode}, log: {log_path}",
        }

    # Find the actual result file (freqtrade appends timestamp)
    result_path = _find_result_file(result_prefix)
    if not result_path:
        return {
            "factor_name": factor_name,
            "run_id": run_id,
            "success": False,
            "error": f"No result file found for prefix {result_prefix}",
        }

    # Parse the result (supports both .json and .zip)
    data = _load_backtest_json(result_path)
    rows, summary = _extract_summary(data, run_id)

    # Write NAV rows to PG
    if dsn and rows:
        write_nav_rows(dsn, rows)

    return {
        "factor_name": factor_name,
        "run_id": run_id,
        "success": True,
        "sharpe": summary.get("sharpe", 0.0),
        "max_drawdown": summary.get("max_drawdown", 0.0),
        "total_profit_pct": summary.get("total_profit_pct", 0.0),
        "n_trades": summary.get("n_rows", 0),
        "log_path": str(log_path),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("factor_name")
    parser.add_argument("--run-date", default="2026-04-10")
    args = parser.parse_args()

    result = run_one(args.factor_name, args.run_date)
    print(json.dumps(result, indent=2))
