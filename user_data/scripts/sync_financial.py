#!/usr/bin/env python3
"""Sprint 1.2 — AI天团 A股财务数据同步脚本.

数据源: 同花顺 THS (东方财富已反爬封禁)
目标表: quant_raw_cn.financial_metrics
用法:   python sync_financial.py [--stocks 000001,000002,...] [--all]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime

import pandas as pd
import psycopg2
import psycopg2.extras
import akshare as ak

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "warehouse",
    "user": "postgres",
    "password": "postgres",
}

DEFAULT_STOCKS = ["000001", "000002", "300750", "600519", "300152"]
STOCK_NAMES = {
    "000001": "平安银行",
    "000002": "万科A",
    "300750": "宁德时代",
    "600519": "贵州茅台",
    "300152": "安诺其",
}

UPSERT_SQL = """
    INSERT INTO quant_raw_cn.financial_metrics (
        stock_code, stock_name, report_date, report_type,
        total_revenue, operating_cost, operating_profit, net_profit, net_profit_deduct,
        total_assets, total_liabilities, shareholders_equity,
        current_assets, current_liabilities,
        operating_cf, investing_cf, financing_cf,
        eps, bvps, roe, roa, gross_margin, net_margin,
        debt_ratio, current_ratio, quick_ratio,
        revenue_yoy, profit_yoy,
        raw_benefit, raw_balance, raw_cashflow, raw_abstract,
        data_source, updated_at
    ) VALUES (
        %(stock_code)s, %(stock_name)s, %(report_date)s, %(report_type)s,
        %(total_revenue)s, %(operating_cost)s, %(operating_profit)s,
        %(net_profit)s, %(net_profit_deduct)s,
        %(total_assets)s, %(total_liabilities)s, %(shareholders_equity)s,
        %(current_assets)s, %(current_liabilities)s,
        %(operating_cf)s, %(investing_cf)s, %(financing_cf)s,
        %(eps)s, %(bvps)s, %(roe)s, %(roa)s, %(gross_margin)s, %(net_margin)s,
        %(debt_ratio)s, %(current_ratio)s, %(quick_ratio)s,
        %(revenue_yoy)s, %(profit_yoy)s,
        %(raw_benefit)s, %(raw_balance)s, %(raw_cashflow)s, %(raw_abstract)s,
        %(data_source)s, NOW()
    )
    ON CONFLICT (stock_code, report_date) DO UPDATE SET
        stock_name        = EXCLUDED.stock_name,
        report_type       = EXCLUDED.report_type,
        total_revenue     = EXCLUDED.total_revenue,
        operating_cost    = EXCLUDED.operating_cost,
        operating_profit  = EXCLUDED.operating_profit,
        net_profit        = EXCLUDED.net_profit,
        net_profit_deduct = EXCLUDED.net_profit_deduct,
        total_assets      = EXCLUDED.total_assets,
        total_liabilities = EXCLUDED.total_liabilities,
        shareholders_equity = EXCLUDED.shareholders_equity,
        current_assets    = EXCLUDED.current_assets,
        current_liabilities = EXCLUDED.current_liabilities,
        operating_cf      = EXCLUDED.operating_cf,
        investing_cf      = EXCLUDED.investing_cf,
        financing_cf      = EXCLUDED.financing_cf,
        eps               = EXCLUDED.eps,
        bvps              = EXCLUDED.bvps,
        roe               = EXCLUDED.roe,
        roa               = EXCLUDED.roa,
        gross_margin      = EXCLUDED.gross_margin,
        net_margin        = EXCLUDED.net_margin,
        debt_ratio        = EXCLUDED.debt_ratio,
        current_ratio     = EXCLUDED.current_ratio,
        quick_ratio       = EXCLUDED.quick_ratio,
        revenue_yoy       = EXCLUDED.revenue_yoy,
        profit_yoy        = EXCLUDED.profit_yoy,
        raw_benefit       = EXCLUDED.raw_benefit,
        raw_balance       = EXCLUDED.raw_balance,
        raw_cashflow      = EXCLUDED.raw_cashflow,
        raw_abstract      = EXCLUDED.raw_abstract,
        data_source       = EXCLUDED.data_source,
        updated_at        = NOW()
"""


# ── Helpers ────────────────────────────────────────────────────────────


def _parse_ths_value(val) -> float | None:
    """Parse THS value like '4.02亿', '-338.93万', '58.85%' into float."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("False", "None", "nan", "—", "-"):
        return None
    # Percent
    if s.endswith("%"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    # Chinese units
    s = s.replace(",", "")
    multiplier = 1
    if "亿" in s:
        multiplier = 1e8
        s = s.replace("亿", "")
    elif "万" in s:
        multiplier = 1e4
        s = s.replace("万", "")
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def _date_from_report_period(rp: str) -> str:
    """Convert THS '报告期' like '2025-12-31' to date."""
    try:
        return pd.Timestamp(rp).strftime("%Y-%m-%d")
    except Exception:
        return rp


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to list of dicts with safe JSON serialization."""
    df = df.where(pd.notnull(df), None)
    return json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))


def _extract_from_row(
    benefit_row: dict | None,
    debt_row: dict | None,
    cash_row: dict | None,
    abstract_row: dict | None,
) -> dict:
    """Extract core metrics from raw THS rows."""

    def g(row, key, default=None):
        if row is None:
            return default
        return _parse_ths_value(row.get(key))

    # Report period
    rp = None
    for r in [benefit_row, debt_row, cash_row, abstract_row]:
        if r and r.get("报告期"):
            rp = r["报告期"]
            break

    return {
        "report_date": _date_from_report_period(rp) if rp else None,
        "report_type": None,  # Will be inferred later
        "total_revenue": g(benefit_row, "*营业总收入") or g(benefit_row, "营业总收入"),
        "operating_cost": g(benefit_row, "*营业总成本") or g(benefit_row, "营业总成本"),
        "operating_profit": g(benefit_row, "三、营业利润") or g(benefit_row, "*营业利润"),
        "net_profit": g(benefit_row, "*归属于母公司所有者的净利润") or g(benefit_row, "*净利润"),
        "net_profit_deduct": g(benefit_row, "*扣除非经常性损益后的净利润"),
        "total_assets": g(debt_row, "*资产合计"),
        "total_liabilities": g(debt_row, "*负债合计"),
        "shareholders_equity": g(debt_row, "*所有者权益（或股东权益）合计"),
        "current_assets": g(debt_row, "流动资产"),
        "current_liabilities": g(debt_row, "流动负债"),
        "operating_cf": g(cash_row, "*经营活动产生的现金流量净额"),
        "investing_cf": g(cash_row, "*投资活动产生的现金流量净额"),
        "financing_cf": g(cash_row, "*筹资活动产生的现金流量净额"),
        "eps": g(abstract_row, "基本每股收益"),
        "bvps": g(abstract_row, "每股净资产"),
        "roe": g(abstract_row, "净资产收益率(ROE)"),
        "roa": g(abstract_row, "总资产报酬率(ROA)"),
        "gross_margin": g(abstract_row, "毛利率"),
        "net_margin": g(abstract_row, "销售净利率"),
        "debt_ratio": g(abstract_row, "资产负债率"),
        "current_ratio": g(abstract_row, "流动比率"),
        "quick_ratio": g(abstract_row, "速动比率"),
    }


def _infer_report_type(rp: str) -> str:
    """Infer report type from period date."""
    try:
        dt = pd.Timestamp(rp)
        m = dt.month
        d = dt.day
        if m == 12 and d == 31:
            return "年报"
        elif m == 6 and d == 30:
            return "半年报"
        elif m == 3 and d == 31:
            return "一季报"
        elif m == 9 and d == 30:
            return "三季报"
    except Exception:
        pass
    return None


def _compute_derived_metrics(rows: list[dict]) -> list[dict]:
    """Compute YoY growth rates by comparing consecutive annual reports."""
    # Build lookup by (stock_code, year) for annual reports
    annual_map: dict[tuple[str, int], dict] = {}
    for r in rows:
        try:
            dt = pd.Timestamp(r["report_date"])
        except Exception:
            continue
        if dt.month == 12 and dt.day == 31:
            annual_map[(r["stock_code"], dt.year)] = r

    for r in rows:
        try:
            dt = pd.Timestamp(r["report_date"])
        except Exception:
            continue
        # YoY for annual reports only
        year = dt.year
        prev = annual_map.get((r["stock_code"], year - 1))
        if prev:
            cur_rev = r.get("total_revenue")
            prev_rev = prev.get("total_revenue")
            if cur_rev and prev_rev and prev_rev != 0:
                r["revenue_yoy"] = round(((cur_rev - prev_rev) / abs(prev_rev)) * 100, 2)
            cur_np = r.get("net_profit")
            prev_np = prev.get("net_profit")
            if cur_np and prev_np and prev_np != 0:
                r["profit_yoy"] = round(((cur_np - prev_np) / abs(prev_np)) * 100, 2)
    return rows


# ── Main Sync Logic ────────────────────────────────────────────────────


def sync_stock(code: str, conn) -> int:
    """Sync one stock's financial data. Returns rows inserted/updated."""
    name = STOCK_NAMES.get(code, code)
    log.info(f"Syncing {name}({code})...")

    # Fetch THS data
    try:
        df_benefit = ak.stock_financial_benefit_ths(symbol=code, indicator="按报告期")
        df_debt = ak.stock_financial_debt_ths(symbol=code, indicator="按报告期")
        df_cash = ak.stock_financial_cash_ths(symbol=code, indicator="按报告期")
    except Exception as e:
        log.error(f"THS fetch failed for {code}: {e}")
        return 0

    # Fetch financial abstract (80+ indicators)
    try:
        df_abstract = ak.stock_financial_abstract(symbol=code)
    except Exception as e:
        log.warning(f"Abstract fetch failed for {code}: {e}")
        df_abstract = None

    # Convert to records
    benefit_recs = _df_to_records(df_benefit)
    debt_recs = _df_to_records(df_debt)
    cash_recs = _df_to_records(df_cash)
    abstract_map = {}
    if df_abstract is not None:
        # financial_abstract has columns: 指标, 20260331, 20251231, ...
        # We transpose so each column becomes a row with {指标: value}
        abst = df_abstract.set_index("指标")
        for col in abst.columns:
            date_str = str(col)
            try:
                d = pd.Timestamp(date_str).strftime("%Y-%m-%d")
            except Exception:
                continue
            abstract_map[d] = abst[col].to_dict()

    # Merge: by report period
    benefit_by_date = {r["报告期"]: r for r in benefit_recs if r.get("报告期")}
    debt_by_date = {r["报告期"]: r for r in debt_recs if r.get("报告期")}
    cash_by_date = {r["报告期"]: r for r in cash_recs if r.get("报告期")}

    all_dates = set(benefit_by_date.keys()) | set(debt_by_date.keys()) | set(cash_by_date.keys())

    rows = []
    count = 0
    for rp in sorted(all_dates):
        b = benefit_by_date.get(rp)
        d = debt_by_date.get(rp)
        c = cash_by_date.get(rp)
        rp_date = _date_from_report_period(rp)
        a = abstract_map.get(rp_date)

        core = _extract_from_row(b, d, c, a)
        report_type = _infer_report_type(rp_date)

        row = {
            "stock_code": code,
            "stock_name": name,
            "report_date": rp_date,
            **core,  # core fields first (report_type=None from _extract_from_row)
            "report_type": report_type,  # then override with inferred type
            "raw_benefit": json.dumps(b, ensure_ascii=False, default=str) if b else None,
            "raw_balance": json.dumps(d, ensure_ascii=False, default=str) if d else None,
            "raw_cashflow": json.dumps(c, ensure_ascii=False, default=str) if c else None,
            "raw_abstract": json.dumps(a, ensure_ascii=False, default=str) if a else None,
            "data_source": "ths",
        }
        # compute derived metrics
        rows.append(row)

    # compute derived metrics
    for r in rows:
        r.setdefault("revenue_yoy", None)
        r.setdefault("profit_yoy", None)
    rows = _compute_derived_metrics(rows)

    # Upsert — use autocommit to prevent cascade failures
    conn.autocommit = True
    cur = conn.cursor()
    written = 0
    for row in rows:
        # Sanitize: replace NaN with None in numeric fields
        for key, val in list(row.items()):
            if isinstance(val, float) and (val != val):  # NaN check
                row[key] = None
        # Sanitize JSON: ensure no NaN in raw fields
        for json_key in ("raw_benefit", "raw_balance", "raw_cashflow", "raw_abstract"):
            raw = row.get(json_key)
            if raw and isinstance(raw, str):
                # Replace NaN inside JSON strings with null
                import re as _re

                raw = _re.sub(r":\s*NaN\b", ": null", raw)
                row[json_key] = raw
        try:
            cur.execute(UPSERT_SQL, row)
            written += 1
        except Exception as e:
            log.warning(f"Upsert failed for {code} {row.get('report_date')}: {e}")
    conn.commit()
    cur.close()

    log.info(f"  {name}({code}): {written} periods synced")
    return written


def main():
    parser = argparse.ArgumentParser(description="Sync A-share financial data via THS")
    parser.add_argument("--stocks", type=str, help="Comma-separated stock codes")
    parser.add_argument("--all", action="store_true", help="Sync all default stocks")
    args = parser.parse_args()

    if args.stocks:
        stocks = [s.strip() for s in args.stocks.split(",")]
    elif args.all:
        stocks = DEFAULT_STOCKS
    else:
        stocks = DEFAULT_STOCKS

    log.info(f"Target stocks: {stocks}")

    conn = psycopg2.connect(**DB_CONFIG)

    total = 0
    for code in stocks:
        n = sync_stock(code, conn)
        total += n

    # Summary
    cur = conn.cursor()
    cur.execute(
        "SELECT stock_code, COUNT(*) FROM quant_raw_cn.financial_metrics GROUP BY stock_code ORDER BY stock_code"
    )
    log.info("─" * 50)
    log.info("Current financial_metrics table:")
    for row in cur.fetchall():
        log.info(f"  {row[0]}: {row[1]} rows")
    cur.close()
    conn.close()

    log.info(f"Done. Total {total} rows synced across {len(stocks)} stocks.")


if __name__ == "__main__":
    main()
