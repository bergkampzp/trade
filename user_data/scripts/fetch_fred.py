#!/usr/bin/env python3
"""Fetch FRED economic indicators and upsert to PostgreSQL."""

import argparse
import logging
import os
import sys

import psycopg2
import psycopg2.extras
from fredapi import Fred


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SERIES = {
    "CPIAUCSL": "CPI (monthly)",
    "FEDFUNDS": "Fed Funds Rate (monthly)",
    "T10Y2Y": "10Y-2Y Spread (daily)",
    "VIXCLS": "VIX (daily)",
    "DTWEXBGS": "DXY (daily)",
    "NAPM": "ISM PMI (monthly)",
}

UPSERT_SQL = """
INSERT INTO quant_raw.macro_indicators (series_id, date, value)
VALUES %s
ON CONFLICT (series_id, date) DO UPDATE SET value = EXCLUDED.value
"""

CREATE_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS quant_raw;
CREATE TABLE IF NOT EXISTS quant_raw.macro_indicators (
    series_id TEXT NOT NULL,
    date      DATE NOT NULL,
    value     DOUBLE PRECISION,
    PRIMARY KEY (series_id, date)
);
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch FRED indicators -> PostgreSQL")
    p.add_argument("--start", default="2023-01-01", help="Start date (YYYY-MM-DD)")
    p.add_argument("--series", nargs="*", help="Subset of series to fetch (default: all)")
    p.add_argument("--dry-run", action="store_true", help="Fetch and print, skip DB write")
    return p.parse_args()


def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def fetch_and_upsert(fred: Fred, conn, series_id: str, start: str, dry_run: bool) -> dict:
    """Fetch one series from FRED, upsert to PG. Returns summary dict."""
    data = fred.get_series(series_id, observation_start=start)
    data = data.dropna()
    if data.empty:
        return {"series": series_id, "count": 0, "range": "N/A"}

    rows = [(series_id, idx.date(), float(val)) for idx, val in data.items()]
    date_min, date_max = rows[0][1], rows[-1][1]
    summary = {
        "series": series_id,
        "count": len(rows),
        "range": f"{date_min} .. {date_max}",
    }

    if dry_run:
        log.info("[DRY-RUN] %s: %d rows (%s)", series_id, len(rows), summary["range"])
        return summary

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, UPSERT_SQL, rows, page_size=500)
    conn.commit()
    return summary


def main():
    args = parse_args()
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        log.error("Set FRED_API_KEY environment variable")
        sys.exit(1)

    dsn = os.environ.get(
        "QUANT_PG_DSN",
        "host=localhost port=5433 dbname=warehouse user=postgres password=postgres",
    )

    fred = Fred(api_key=api_key)
    targets = args.series if args.series else list(SERIES.keys())
    unknown = set(targets) - set(SERIES.keys())
    if unknown:
        log.error("Unknown series: %s. Available: %s", unknown, list(SERIES.keys()))
        sys.exit(1)

    conn = None
    if not args.dry_run:
        conn = psycopg2.connect(dsn)
        ensure_table(conn)

    summaries = []
    for sid in targets:
        try:
            s = fetch_and_upsert(fred, conn, sid, args.start, args.dry_run)
            summaries.append(s)
        except Exception:
            log.warning("Failed to fetch %s, skipping", sid, exc_info=True)

    if conn:
        conn.close()

    # Print summary table
    print(f"\n{'Series':<12} {'Count':>6}  {'Date Range'}")
    print("-" * 46)
    for s in summaries:
        print(f"{s['series']:<12} {s['count']:>6}  {s['range']}")
    print()


if __name__ == "__main__":
    main()
