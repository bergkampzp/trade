#!/usr/bin/env python3
"""
sync_openbb.py — OpenBB → PostgreSQL 宏观经济指标统一同步

替代 sync_macro.py，使用 OpenBB 统一抽象层替代 fredapi + yfinance 直接调用。
Provider 通过参数切换，支持自动 fallback。

用法:
  python sync_openbb.py                      # 同步全部指标 (fred)
  python sync_openbb.py --provider yfinance  # 使用 yfinance
  python sync_openbb.py --dry-run            # 只预览不写入
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_openbb")

# ── 宏观经济指标定义 ──────────────────────────────────
# 每个指标: {series_id, name, fred_symbol, yf_symbol?, frequency}
INDICATORS = [
    # ── 价格与通胀 (PCE/CPI) ──
    {"series_id": "CPIAUCSL", "name": "CPI", "fred_symbol": "CPIAUCSL", "frequency": "monthly"},
    {"series_id": "PCEPI", "name": "PCE", "fred_symbol": "PCEPI", "frequency": "monthly"},
    {"series_id": "PPIACO", "name": "PPI", "fred_symbol": "PPIACO", "frequency": "monthly"},
    # ── 货币政策 ──
    {
        "series_id": "FEDFUNDS",
        "name": "Fed Funds Rate",
        "fred_symbol": "FEDFUNDS",
        "frequency": "monthly",
    },
    {"series_id": "M2SL", "name": "M2 Money Supply", "fred_symbol": "M2SL", "frequency": "monthly"},
    # ── 就业 ──
    {
        "series_id": "UNRATE",
        "name": "Unemployment",
        "fred_symbol": "UNRATE",
        "frequency": "monthly",
    },
    {
        "series_id": "PAYEMS",
        "name": "Nonfarm Payroll",
        "fred_symbol": "PAYEMS",
        "frequency": "monthly",
    },
    # ── 市场波动 ──
    {
        "series_id": "VIXCLS",
        "name": "VIX",
        "fred_symbol": "VIXCLS",
        "frequency": "daily",
        "yf_symbol": "^VIX",
    },
    {
        "series_id": "DTWEXBGS",
        "name": "DXY",
        "fred_symbol": "DTWEXBGS",
        "frequency": "daily",
        "yf_symbol": "DX-Y.NYB",
    },
    # ── 利率 ──
    {"series_id": "T10Y2Y", "name": "10Y-2Y Spread", "fred_symbol": "T10Y2Y", "frequency": "daily"},
    {
        "series_id": "DGS10",
        "name": "10Y Treasury",
        "fred_symbol": "DGS10",
        "frequency": "daily",
        "yf_symbol": "^TNX",
    },
    {"series_id": "DGS2", "name": "2Y Treasury", "fred_symbol": "DGS2", "frequency": "daily"},
    {"series_id": "DFII10", "name": "10Y TIPS", "fred_symbol": "DFII10", "frequency": "daily"},
    # ── 实体经济 ──
    {
        "series_id": "INDPRO",
        "name": "Industrial Prod",
        "fred_symbol": "INDPRO",
        "frequency": "monthly",
    },
    {"series_id": "RSAFS", "name": "Retail Sales", "fred_symbol": "RSAFS", "frequency": "monthly"},
    {
        "series_id": "HOUST",
        "name": "Housing Starts",
        "fred_symbol": "HOUST",
        "frequency": "monthly",
    },
    # ── 消费 ──
    {
        "series_id": "UMCSENT",
        "name": "Consumer Sentiment",
        "fred_symbol": "UMCSENT",
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


def load_fred_key() -> str | None:
    """从 OpenBB 配置文件加载 FRED API Key."""
    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    if not os.path.exists(settings_path):
        return None
    with open(settings_path) as f:
        return json.load(f).get("fred", {}).get("api_key")


def fetch_via_openbb(indicator: dict) -> pd.DataFrame:
    """通过 OpenBB + FRED provider 获取指标数据."""
    from openbb import obb

    key = os.environ.get("FRED_API_KEY") or load_fred_key()
    if not key:
        log.error("FRED_API_KEY 未设置")
        sys.exit(1)

    obb.user.credentials.fred_api_key = key

    try:
        result = obb.economy.fred_series(
            symbol=indicator["fred_symbol"],
            provider="fred",
        )
        df = result.to_df()
        if df.empty:
            log.warning("  %s: OpenBB 返回空数据", indicator["name"])
            return pd.DataFrame()

        # OpenBB fred_series 返回的列名是 symbol 本身（如 'CPIAUCSL'）
        value_col = df.columns[0]
        df = df.reset_index()
        df = df.rename(columns={df.columns[0]: "date", value_col: "value"})
        df["series_id"] = indicator["series_id"]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df["value"] = df["value"].astype(float)
        return df[["series_id", "date", "value"]]
    except Exception as e:
        log.error("  %s: OpenBB 失败 (%s)", indicator["name"], e)
        return pd.DataFrame()


def fetch_via_yfinance(indicator: dict) -> pd.DataFrame:
    """通过 yfinance 获取指标数据 (fallback)."""
    import yfinance as yf

    symbol = indicator.get("yf_symbol")
    if not symbol:
        log.warning("  %s: 无 yfinance symbol, 跳过", indicator["name"])
        return pd.DataFrame()

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="max", interval="1d")
        if df.empty:
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


def main():
    args = parse_args()

    dsn = os.environ.get("QUANT_PG_DSN", DEFAULT_DSN)
    conn = None
    if not args.dry_run:
        conn = psycopg2.connect(dsn)

    total_rows = 0
    print(f"\n{'=' * 60}")
    print(f"  OpenBB Macro Sync → PostgreSQL")
    print(f"  Provider: {args.provider}  {'(dry-run)' if args.dry_run else ''}")
    print(f"  Indicators: {len(INDICATORS)}")
    print(f"{'=' * 60}\n")

    for ind in INDICATORS:
        log.info("Fetching %s (%s)...", ind["name"], ind["series_id"])

        if args.provider == "fred":
            df = fetch_via_openbb(ind)
        else:
            df = fetch_via_yfinance(ind)

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
        print(f"  {ind['series_id']:<12} {len(df):>6}  {date_range}  [{ind['frequency']}]")
        total_rows += len(df)

    if conn:
        conn.close()

    print(f"\n{'=' * 60}")
    print(f"  Total: {total_rows} rows synced ({len([i for i in INDICATORS if i])} indicators)")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
