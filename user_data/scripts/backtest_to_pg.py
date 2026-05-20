"""Parse freqtrade backtest JSON and write an equity curve to quant.mart_backtest_nav.

Usage:
    python backtest_to_pg.py <backtest-result.json> [--run-id RUN_ID]

Environment:
    QUANT_PG_DSN   Postgres DSN (defaults to localhost:5433 warehouse)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values


DEFAULT_PG_DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"

DELETE_SQL = "DELETE FROM quant.mart_backtest_nav WHERE run_id = %s"

INSERT_SQL = """
    INSERT INTO quant.mart_backtest_nav
        (run_id, date, nav, sharpe, max_drawdown, total_profit_pct)
    VALUES %s
"""


def parse_backtest(
    json_path: Path, run_id: str | None = None
) -> tuple[str, list[tuple], dict[str, Any]]:
    """Parse a freqtrade backtest JSON into NAV rows.

    Returns (run_id, rows, summary) where each row is
    (run_id, date, nav, sharpe, max_drawdown, total_profit_pct).
    """
    json_path = Path(json_path)
    with json_path.open() as f:
        data = json.load(f)

    strategies = data["strategy"]
    if not strategies:
        raise ValueError(f"No strategy found in {json_path}")
    # Pick the single strategy in the file (freqtrade writes one per file).
    strategy_name = next(iter(strategies))
    s = strategies[strategy_name]

    daily_profit = s.get("daily_profit") or []
    if not daily_profit:
        raise ValueError(f"daily_profit is empty in {json_path}")

    starting_balance = float(s["starting_balance"])
    sharpe = float(s.get("sharpe") or 0.0)
    max_drawdown = float(s.get("max_drawdown_account") or 0.0)
    total_profit_pct = float(s.get("profit_total") or 0.0) * 100.0

    if run_id is None:
        run_id = json_path.stem

    rows: list[tuple] = []
    nav = starting_balance
    for entry in daily_profit:
        date_str, profit = entry[0], float(entry[1])
        nav += profit
        rows.append((run_id, date_str, nav, sharpe, max_drawdown, total_profit_pct))

    summary = {
        "strategy_name": strategy_name,
        "starting_balance": starting_balance,
        "final_balance": float(s.get("final_balance") or nav),
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "total_profit_pct": total_profit_pct,
        "n_rows": len(rows),
    }
    return run_id, rows, summary


def write_nav_rows(dsn: str, rows: list[tuple]) -> None:
    """Idempotent upsert: delete-then-insert all rows for the run_id in one tx."""
    if not rows:
        return
    run_id = rows[0][0]
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL, (run_id,))
            execute_values(cur, INSERT_SQL, rows, page_size=1000)
        conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    run_id, rows, summary = parse_backtest(args.json_path, run_id=args.run_id)
    dsn = os.environ.get("QUANT_PG_DSN", DEFAULT_PG_DSN)
    write_nav_rows(dsn, rows)
    print(
        f"wrote {len(rows)} NAV rows for run_id={run_id} "
        f"(strategy={summary['strategy_name']}, "
        f"sharpe={summary['sharpe']:.3f}, "
        f"total_profit={summary['total_profit_pct']:.2f}%, "
        f"max_dd={summary['max_drawdown']:.2%})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
