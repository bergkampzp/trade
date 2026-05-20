"""Factor Research Loop orchestrator.

Usage:
    python run_research_loop.py --factors all
    python run_research_loop.py --factors momentum_24h,rsi_14
    python run_research_loop.py --factors all --skip-dbt --skip-tier3
    python run_research_loop.py --dry-run
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg2


# Ensure sibling scripts are importable
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from compute_correlation_filter import get_max_corr_with_accepted  # noqa: E402
from factor_registry import load_factor_names  # noqa: E402
from run_single_factor_backtest import run_one  # noqa: E402


logger = logging.getLogger(__name__)

DEFAULT_PG_DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"
DBT_PROJECT_DIR = "/home/zp/airbyte/quant_warehouse"

# Tier thresholds
# Adjusted for crypto 1h: typical IC is 0.005-0.01 (lower than equities)
TIER1_IC_MEAN = 0.005
TIER1_IC_IR = 0.3
TIER2_QUANTILE_SHARPE = 0.8
TIER2_MAX_CORR = 0.7
TIER3_SHARPE = 1.0
TIER3_MAX_DD = 0.15

UPSERT_SQL = """
INSERT INTO quant.mart_factor_scoreboard
    (factor_name, run_date, tier1_pass, tier2_pass, tier3_pass,
     ic_mean, ic_ir, quantile_sharpe, max_corr_with_accepted,
     backtest_sharpe, backtest_max_dd, backtest_total_profit_pct,
     verdict, notes, updated_at)
VALUES
    (%(factor_name)s, %(run_date)s, %(tier1_pass)s, %(tier2_pass)s, %(tier3_pass)s,
     %(ic_mean)s, %(ic_ir)s, %(quantile_sharpe)s, %(max_corr_with_accepted)s,
     %(backtest_sharpe)s, %(backtest_max_dd)s, %(backtest_total_profit_pct)s,
     %(verdict)s, %(notes)s, NOW())
ON CONFLICT (factor_name, run_date) DO UPDATE SET
    tier1_pass = EXCLUDED.tier1_pass,
    tier2_pass = EXCLUDED.tier2_pass,
    tier3_pass = EXCLUDED.tier3_pass,
    ic_mean = EXCLUDED.ic_mean,
    ic_ir = EXCLUDED.ic_ir,
    quantile_sharpe = EXCLUDED.quantile_sharpe,
    max_corr_with_accepted = EXCLUDED.max_corr_with_accepted,
    backtest_sharpe = EXCLUDED.backtest_sharpe,
    backtest_max_dd = EXCLUDED.backtest_max_dd,
    backtest_total_profit_pct = EXCLUDED.backtest_total_profit_pct,
    verdict = EXCLUDED.verdict,
    notes = EXCLUDED.notes,
    updated_at = NOW()
"""


def phase1_load_registry(factor_filter: str) -> list[str]:
    """Phase 1: Load factor registry, apply filter."""
    all_names = load_factor_names()
    if factor_filter == "all":
        names = all_names
    else:
        requested = [n.strip() for n in factor_filter.split(",")]
        unknown = set(requested) - set(all_names)
        if unknown:
            raise ValueError(f"Unknown factors: {unknown}. Valid: {all_names}")
        names = requested
    logger.info("Phase 1: %d factors loaded: %s", len(names), names)
    return names


def phase2_dbt_refresh(skip: bool) -> None:
    """Phase 2: Run dbt to refresh all mart models."""
    if skip:
        logger.info("Phase 2: dbt refresh SKIPPED")
        return
    logger.info("Phase 2: Running dbt refresh...")
    cmd = ["dbt", "run", "--select", "staging+ intermediate+ features+ mart_hourly_signals+"]
    result = subprocess.run(cmd, cwd=DBT_PROJECT_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("dbt run failed:\n%s", result.stdout + result.stderr)
        raise RuntimeError("dbt run failed")
    logger.info("Phase 2: dbt refresh completed")


def phase3_tier1(dsn: str, factors: list[str]) -> dict[str, dict]:
    """Phase 3: Tier 1 IC filter. Returns {factor: {ic_mean, ic_ir, pass}}."""
    results = {}
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT factor_name, ic_mean, ic_ir, ic_t_stat
                FROM quant.mart_factor_ic_extended
                WHERE window_label = 'overall'
            """)
            for row in cur.fetchall():
                name, ic_mean, ic_ir, ic_t = row
                if name not in factors:
                    continue
                ic_mean_f = float(ic_mean) if ic_mean else 0.0
                ic_ir_f = float(ic_ir) if ic_ir else 0.0
                passed = abs(ic_mean_f) >= TIER1_IC_MEAN and abs(ic_ir_f) >= TIER1_IC_IR
                results[name] = {
                    "ic_mean": ic_mean_f,
                    "ic_ir": ic_ir_f,
                    "tier1_pass": passed,
                }

    # Factors not in IC table (data issues) → fail
    for f in factors:
        if f not in results:
            results[f] = {"ic_mean": 0.0, "ic_ir": 0.0, "tier1_pass": False}

    survivors = [f for f, r in results.items() if r["tier1_pass"]]
    logger.info(
        "Phase 3 Tier 1: %d/%d passed (|IC|≥%.3f AND |IR|≥%.1f): %s",
        len(survivors),
        len(factors),
        TIER1_IC_MEAN,
        TIER1_IC_IR,
        survivors,
    )
    return results


def phase4_tier2(dsn: str, tier1_results: dict[str, dict]) -> dict[str, dict]:
    """Phase 4: Tier 2 quantile Sharpe + correlation filter."""
    survivors = [f for f, r in tier1_results.items() if r["tier1_pass"]]
    if not survivors:
        logger.info("Phase 4 Tier 2: no Tier 1 survivors, skipping")
        return tier1_results

    # Get quantile Sharpe
    quantile_sharpe = {}
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT factor_name, sharpe_annualized
                FROM quant.mart_factor_quantile_backtest
            """)
            for row in cur.fetchall():
                quantile_sharpe[row[0]] = float(row[1]) if row[1] else 0.0

    # Get max correlation with accepted factors
    max_corr = get_max_corr_with_accepted(dsn)

    for f in survivors:
        qs = quantile_sharpe.get(f, 0.0)
        mc = max_corr.get(f, 0.0)
        sharpe_ok = abs(qs) >= TIER2_QUANTILE_SHARPE
        corr_ok = mc <= TIER2_MAX_CORR
        tier1_results[f]["quantile_sharpe"] = qs
        tier1_results[f]["max_corr_with_accepted"] = mc
        tier1_results[f]["tier2_pass"] = sharpe_ok and corr_ok
        if not sharpe_ok:
            tier1_results[f]["verdict"] = "FAIL_TIER2_SHARPE"
        elif not corr_ok:
            tier1_results[f]["verdict"] = "FAIL_TIER2_CORR"

    tier2_survivors = [f for f in survivors if tier1_results[f].get("tier2_pass")]
    logger.info(
        "Phase 4 Tier 2: %d/%d passed (Sharpe≥%.1f AND corr≤%.1f): %s",
        len(tier2_survivors),
        len(survivors),
        TIER2_QUANTILE_SHARPE,
        TIER2_MAX_CORR,
        tier2_survivors,
    )
    return tier1_results


def phase5_tier3(dsn: str, results: dict[str, dict], run_date: str, skip: bool) -> dict[str, dict]:
    """Phase 5: Tier 3 freqtrade full backtest."""
    survivors = [f for f, r in results.items() if r.get("tier2_pass")]
    if not survivors or skip:
        if skip:
            logger.info("Phase 5 Tier 3: SKIPPED")
        else:
            logger.info("Phase 5 Tier 3: no Tier 2 survivors, skipping")
        return results

    logger.info("Phase 5 Tier 3: running backtest for %d factors: %s", len(survivors), survivors)
    for f in survivors:
        bt = run_one(f, run_date, dsn=dsn)
        if not bt["success"]:
            results[f]["tier3_pass"] = False
            results[f]["verdict"] = "FAIL_TIER3_ERROR"
            results[f]["notes"] = bt.get("error", "")
            logger.warning("Tier 3 FAILED for %s: %s", f, bt.get("error"))
            continue

        sharpe = bt["sharpe"]
        max_dd = bt["max_drawdown"]
        results[f]["backtest_sharpe"] = sharpe
        results[f]["backtest_max_dd"] = max_dd
        results[f]["backtest_total_profit_pct"] = bt["total_profit_pct"]

        sharpe_ok = sharpe >= TIER3_SHARPE
        dd_ok = max_dd <= TIER3_MAX_DD
        results[f]["tier3_pass"] = sharpe_ok and dd_ok

        if not sharpe_ok:
            results[f]["verdict"] = "FAIL_TIER3_SHARPE"
        elif not dd_ok:
            results[f]["verdict"] = "FAIL_TIER3_DD"
        else:
            results[f]["verdict"] = "PASS"

        logger.info(
            "Tier 3 %s: sharpe=%.3f max_dd=%.2f%% → %s",
            f,
            sharpe,
            max_dd * 100,
            results[f]["verdict"],
        )

    return results


def phase6_write_scoreboard(dsn: str, results: dict[str, dict], run_date: str) -> None:
    """Phase 6: Upsert scoreboard rows to PG."""
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            for f, r in results.items():
                # Set verdict for non-Tier1 failures
                if not r.get("verdict"):
                    if not r.get("tier1_pass"):
                        r["verdict"] = "FAIL_TIER1"
                    else:
                        r["verdict"] = "SKIPPED"

                params = {
                    "factor_name": f,
                    "run_date": run_date,
                    "tier1_pass": r.get("tier1_pass"),
                    "tier2_pass": r.get("tier2_pass"),
                    "tier3_pass": r.get("tier3_pass"),
                    "ic_mean": r.get("ic_mean"),
                    "ic_ir": r.get("ic_ir"),
                    "quantile_sharpe": r.get("quantile_sharpe"),
                    "max_corr_with_accepted": r.get("max_corr_with_accepted"),
                    "backtest_sharpe": r.get("backtest_sharpe"),
                    "backtest_max_dd": r.get("backtest_max_dd"),
                    "backtest_total_profit_pct": r.get("backtest_total_profit_pct"),
                    "verdict": r["verdict"],
                    "notes": r.get("notes"),
                }
                cur.execute(UPSERT_SQL, params)
        conn.commit()
    logger.info("Phase 6: wrote %d scoreboard rows for run_date=%s", len(results), run_date)


def phase7_report(results: dict[str, dict], run_date: str) -> str:
    """Phase 7: Generate markdown report."""
    lines = [
        f"# Factor Research Loop Report — {run_date}",
        "",
        f"**Factors evaluated:** {len(results)}",
        "",
        "## Tier Progression",
        "",
        "| Tier | Passed |",
        "|------|--------|",
        f"| Tier 1 (IC) | {sum(1 for r in results.values() if r.get('tier1_pass'))} |",
        f"| Tier 2 (Quantile+Corr) | {sum(1 for r in results.values() if r.get('tier2_pass'))} |",
        f"| Tier 3 (Backtest) | {sum(1 for r in results.values() if r.get('tier3_pass'))} |",
        "",
        "## Scoreboard",
        "",
        "| Factor | IC Mean | IC IR | Q-Sharpe | Max Corr | BT Sharpe | BT MaxDD | Verdict |",
        "|--------|---------|-------|----------|----------|-----------|----------|---------|",
    ]

    sorted_results = sorted(results.items(), key=lambda x: x[1].get("verdict", "Z"))
    for f, r in sorted_results:
        ic_mean = f"{r.get('ic_mean', 0):.4f}" if r.get("ic_mean") is not None else "-"
        ic_ir = f"{r.get('ic_ir', 0):.3f}" if r.get("ic_ir") is not None else "-"
        qs = f"{r.get('quantile_sharpe', 0):.2f}" if r.get("quantile_sharpe") is not None else "-"
        mc = (
            f"{r.get('max_corr_with_accepted', 0):.3f}"
            if r.get("max_corr_with_accepted") is not None
            else "-"
        )
        bs = f"{r.get('backtest_sharpe', 0):.3f}" if r.get("backtest_sharpe") is not None else "-"
        bd = f"{r.get('backtest_max_dd', 0):.2%}" if r.get("backtest_max_dd") is not None else "-"
        v = r.get("verdict", "UNKNOWN")
        lines.append(f"| {f} | {ic_mean} | {ic_ir} | {qs} | {mc} | {bs} | {bd} | {v} |")

    lines.append("")
    report = "\n".join(lines)

    # Write to file
    report_path = Path(tempfile.gettempdir()) / f"sprint2_report_{run_date}.md"
    report_path.write_text(report)
    logger.info("Phase 7: report written to %s", report_path)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Factor Research Loop")
    parser.add_argument("--factors", default="all", help="Comma-separated factor names or 'all'")
    parser.add_argument("--skip-dbt", action="store_true", help="Skip dbt refresh")
    parser.add_argument("--skip-tier3", action="store_true", help="Skip Tier 3 backtest")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, no writes")
    parser.add_argument("--run-date", default=None, help="Run date (default: today)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    dsn = os.environ.get("QUANT_PG_DSN", DEFAULT_PG_DSN)
    run_date = args.run_date or datetime.date.today().isoformat()

    # Phase 1
    factors = phase1_load_registry(args.factors)

    if args.dry_run:
        print(f"DRY RUN: would evaluate {len(factors)} factors: {factors}")
        return 0

    # Phase 2
    phase2_dbt_refresh(args.skip_dbt)

    # Phase 3
    results = phase3_tier1(dsn, factors)

    # Phase 4
    results = phase4_tier2(dsn, results)

    # Phase 5
    results = phase5_tier3(dsn, results, run_date, args.skip_tier3)

    # Phase 6
    phase6_write_scoreboard(dsn, results, run_date)

    # Phase 7
    report = phase7_report(results, run_date)
    print(report)

    # Summary
    passed = [f for f, r in results.items() if r.get("verdict") == "PASS"]
    if passed:
        print(f"\n✓ {len(passed)} factors PASSED: {passed}")
    else:
        print("\n✗ No factors passed all 3 tiers")

    return 0


if __name__ == "__main__":
    sys.exit(main())
