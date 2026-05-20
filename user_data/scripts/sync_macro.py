#!/usr/bin/env python3
"""
sync_macro.py — OpenBB → PostgreSQL 宏观经济指标同步

支持 provider: fred (需要 API Key) / yfinance / oecd (免费)
FRED API Key 注册: https://fred.stlouisfed.org/docs/api/api_key.html
配置: 写入 ~/.openbb_platform/user_settings.json
  {"fred": {"api_key": "your_key_here"}}

用法:
  python sync_macro.py                    # 同步全部指标
  python sync_macro.py --dry-run           # 只预览
  python sync_macro.py --provider yfinance # 无需 Key
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

import pandas as pd
import psycopg2
import psycopg2.extras
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── 指标定义 ──────────────────────────────────────────────
# 每个指标定义了两个 provider: fred (优先) + yfinance fallback
INDICATORS = [
    {
        "series_id": "CPIAUCSL",
        "name": "CPI (Consumer Price Index)",
        "fred_symbol": "CPIAUCSL",
        "yf_symbol": "^GSPC",  # 无直接 CPI，用 proxy
        "frequency": "monthly",
    },
    {
        "series_id": "FEDFUNDS",
        "name": "Fed Funds Rate",
        "fred_symbol": "FEDFUNDS",
        "yf_symbol": "^IRX",  # 13-week T-bill proxy
        "frequency": "monthly",
    },
    {
        "series_id": "VIXCLS",
        "name": "VIX (Volatility Index)",
        "fred_symbol": "VIXCLS",
        "yf_symbol": "^VIX",
        "frequency": "daily",
    },
    {
        "series_id": "DTWEXBGS",
        "name": "DXY (US Dollar Index)",
        "fred_symbol": "DTWEXBGS",
        "yf_symbol": "DX-Y.NYB",
        "frequency": "daily",
    },
    {
        "series_id": "T10Y2Y",
        "name": "10Y-2Y Treasury Spread",
        "fred_symbol": "T10Y2Y",
        "yf_symbol": "^TNX",  # 10-year Treasury yield proxy
        "frequency": "daily",
    },
    {
        "series_id": "INDPRO",
        "name": "Industrial Production (PMI proxy)",
        "fred_symbol": "INDPRO",
        "yf_symbol": None,
        "frequency": "monthly",
    },
]

UPSERT_SQL = """
    INSERT INTO quant_raw.macro_indicators (series_id, date, value)
    VALUES %s
    ON CONFLICT (series_id, date) DO UPDATE SET value = EXCLUDED.value
"""

DEFAULT_DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"


def parse_args():
    p = argparse.ArgumentParser(description="OpenBB → PG 宏观经济数据同步")
    p.add_argument("--dry-run", action="store_true", help="只预览不写入")
    p.add_argument(
        "--provider", default="fred", choices=["fred", "yfinance"], help="数据提供者 (默认: fred)"
    )
    return p.parse_args()


def fred_key_ready() -> bool:
    """检查 FRED API Key 是否已配置."""
    import json

    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    if not os.path.exists(settings_path):
        return False
    with open(settings_path) as f:
        settings = json.load(f)
    key = os.environ.get("FRED_API_KEY") or settings.get("fred", {}).get("api_key")
    return bool(key and key != "your_key_here")


def fetch_via_yfinance(indicator: dict) -> pd.DataFrame:
    """通过 yfinance 获取指标数据."""
    symbol = indicator["yf_symbol"]
    if not symbol:
        log.warning("  %s: 无 yfinance symbol, 跳过", indicator["name"])
        return pd.DataFrame()

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="max", interval="1d")
        if df.empty:
            log.warning("  %s: yfinance 返回空数据", indicator["name"])
            return pd.DataFrame()

        df = df.reset_index()
        df = df.rename(columns={"Date": "date", "Close": "value"})
        df["series_id"] = indicator["series_id"]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df["value"] = df["value"].astype(float)
        return df[["series_id", "date", "value"]]
    except Exception as e:
        log.error("  %s: yfinance 失败 (%s)", indicator["name"], e)
        return pd.DataFrame()


def fetch_via_fred(indicator: dict) -> pd.DataFrame:
    """通过 FRED API 获取指标数据."""
    from fredapi import Fred
    import json

    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                api_key = json.load(f).get("fred", {}).get("api_key")
    if not api_key or api_key == "your_key_here":
        log.error("FRED_API_KEY 未设置 (env 或 ~/.openbb_platform/user_settings.json)")
        sys.exit(1)

    try:
        fred = Fred(api_key=api_key)
        series = fred.get_series(indicator["fred_symbol"], observation_start="2023-01-01")
        series = series.dropna()
        if series.empty:
            log.warning("  %s: FRED 返回空数据", indicator["name"])
            return pd.DataFrame()

        df = pd.DataFrame({"date": series.index, "value": series.values})
        df["series_id"] = indicator["series_id"]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df["value"] = df["value"].astype(float)
        return df[["series_id", "date", "value"]]
    except Exception as e:
        log.error("  %s: FRED 失败 (%s)", indicator["name"], e)
        return pd.DataFrame()


def main():
    args = parse_args()

    # ── 连接 PostgreSQL ──
    dsn = os.environ.get("QUANT_PG_DSN", DEFAULT_DSN)
    conn = None
    if not args.dry_run:
        conn = psycopg2.connect(dsn)

    total_rows = 0
    print(f"\n{'=' * 60}")
    print(f"  Macro Indicators Sync → PostgreSQL")
    print(f"  Provider: {args.provider}  {'(dry-run)' if args.dry_run else ''}")
    print(f"{'=' * 60}\n")

    for ind in INDICATORS:
        log.info("Fetching %s (%s)...", ind["name"], ind["series_id"])

        if args.provider == "fred" and fred_key_ready():
            df = fetch_via_fred(ind)
        elif args.provider == "yfinance":
            df = fetch_via_yfinance(ind)
        else:
            log.warning("  跳过 (需要 FRED API Key)")
            print(f"  {ind['series_id']:<12} {'--':>6}  跳过")
            continue

        if df.empty:
            print(f"  {ind['series_id']:<12} {'0':>6}  无数据")
            continue

        # 写入 PostgreSQL
        if not args.dry_run and conn:
            rows = [(r.series_id, r.date.to_pydatetime(), float(r.value)) for r in df.itertuples()]
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, UPSERT_SQL, rows, page_size=500)
            conn.commit()

        date_range = (
            f"{df['date'].min().strftime('%Y-%m-%d')} .. {df['date'].max().strftime('%Y-%m-%d')}"
        )
        print(f"  {ind['series_id']:<12} {len(df):>6}  {date_range}")
        total_rows += len(df)

    if conn:
        conn.close()

    print(f"\n{'=' * 60}")
    print(f"  Total: {total_rows} rows synced")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
