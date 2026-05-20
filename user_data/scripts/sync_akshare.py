#!/usr/bin/env python3
"""
sync_akshare.py — A 股数据同步脚本 (AKShare → PostgreSQL)

用途:
    从 AKShare 获取 A 股日线数据、基本面快照，写入 quant_raw_cn schema

用法:
    # 同步指定股票 (沪深300 前10只)
    python3 sync_akshare.py --stocks 000001,000002,600519 --days-back 365

    # 同步沪深300 全部成分股
    python3 sync_akshare.py --index CSI300 --days-back 365

    # 增量同步最近 5 天
    python3 sync_akshare.py --index CSI300 --days-back 5

依赖:
    pip install akshare psycopg2-binary pandas
"""

import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sync_akshare")

DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"

# 沪深300 成分股 (核心前 20 只)
CSI300_TOP20 = [
    "000001",
    "000002",
    "000333",
    "000568",
    "000651",
    "000858",
    "002304",
    "002415",
    "002475",
    "002714",
    "300015",
    "300059",
    "300124",
    "300274",
    "300750",
    "600036",
    "600519",
    "600690",
    "600900",
    "601012",
]

# 沪深300 全量成分股 (通过 AKShare 获取)
CSI300_FULL_URL = "http://www.csi.com.cn/csindex/quote/zstotal/000300"


def _get_csi300_constituents() -> list[str]:
    """通过 akshare 获取沪深300 成分股列表。"""
    try:
        import akshare as ak

        df = ak.index_stock_cons_csindex("000300")
        # 列通常包含: 指数代码, 成分券代码, 成分券名称
        for col in df.columns:
            if "代码" in col or "code" in col.lower():
                codes = df[col].astype(str).str.strip().str.zfill(6).tolist()
                logger.info(f"从 AKShare 获取到 {len(codes)} 只沪深300成分股")
                return codes
        logger.warning("未找到代码列，使用默认沪深300 top20")
        return CSI300_TOP20
    except Exception as e:
        logger.warning(f"获取沪深300成分股失败: {e}，使用默认列表")
        return CSI300_TOP20


def sync_daily(
    stock_codes: list[str],
    days_back: int = 365,
    batch_size: int = 5,
    force: bool = False,
) -> dict:
    """同步 A 股日线数据 (AKShare → PostgreSQL)

    Returns:
        {total: N, inserted: N, failed: [codes]}
    """
    import akshare as ak
    import psycopg2
    import pandas as pd

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")

    total = 0
    inserted = 0
    failed = []

    start_ts = datetime.utcnow()

    for code in stock_codes:
        try:
            # 降级链: 东方财富 → 腾讯 → 新浪
            df = pd.DataFrame()
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start,
                    end_date=end,
                    adjust="qfq",
                )
                logger.info(f"  东方财富接口成功: {code}")
            except Exception as e:
                logger.warning(f"  东方财富接口失败 ({code}): {e}，尝试腾讯财经接口")
                try:
                    # 腾讯股票代码前缀
                    tencent_sym = (
                        f"sz{code}" if code.startswith("0") or code.startswith("3") else f"sh{code}"
                    )
                    df = ak.stock_zh_a_daily(
                        symbol=tencent_sym,
                        start_date=datetime.now().strftime("%Y%m%d"),
                        end_date=datetime.now().strftime("%Y%m%d"),
                        adjust="qfq",
                    )
                    df["股票代码"] = code
                    logger.info(f"  腾讯接口成功: {code}")
                except Exception as e2:
                    logger.error(f"  腾讯接口也失败 ({code}): {e2}")
                    failed.append(code)
                    time.sleep(3)
                    continue

            if df.empty:
                logger.info(f"  ⏭ {code}: 无数据")
                continue

            rows_affected = 0
            for _, row in df.iterrows():
                date = row.get("日期")
                if pd.isna(date):
                    continue

                # 检查是否已存在 (upsert)
                if not force:
                    cur.execute(
                        "SELECT 1 FROM quant_raw_cn.akshare_daily WHERE stock_code=%s AND trade_date=%s",
                        (code, date),
                    )
                    if cur.fetchone():
                        continue

                cur.execute(
                    """INSERT INTO quant_raw_cn.akshare_daily
                    (stock_code, trade_date, open, high, low, close, volume, amount,
                     amplitude, change_pct, change_amt, turnover_rate)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, volume=EXCLUDED.volume,
                        amount=EXCLUDED.amount, amplitude=EXCLUDED.amplitude,
                        change_pct=EXCLUDED.change_pct, change_amt=EXCLUDED.change_amt,
                        turnover_rate=EXCLUDED.turnover_rate""",
                    (
                        code,
                        date,
                        float(row.get("开盘", 0)),
                        float(row.get("最高", 0)),
                        float(row.get("最低", 0)),
                        float(row.get("收盘", 0)),
                        int(row.get("成交量", 0)),
                        float(row.get("成交额", 0) or 0),
                        float(row.get("振幅", 0) or 0),
                        float(row.get("涨跌幅", 0) or 0),
                        float(row.get("涨跌额", 0) or 0),
                        float(row.get("换手率", 0) or 0),
                    ),
                )
                rows_affected += 1

            conn.commit()
            total += len(df)
            inserted += rows_affected
            logger.info(f"  ✅ {code}: {len(df)} 条, 新增 {rows_affected}")

        except Exception as e:
            conn.rollback()
            failed.append(code)
            logger.error(f"  ❌ {code}: {e}")

        # 限速: 避免触发 AKShare 频率限制
        # 东方财富反爬严格，需要更长间隔
        import random

        time.sleep(random.uniform(2.0, 4.0))

    cur.close()
    conn.close()

    dur = (datetime.utcnow() - start_ts).total_seconds()
    logger.info(f"完成: {total} 条, 新增 {inserted}, 失败 {len(failed)}, 耗时 {dur:.1f}s")

    return {"total": total, "inserted": inserted, "failed": failed, "duration_s": dur}


def sync_fundamentals(stock_codes: list[str]) -> dict:
    """同步 A 股基本面摘要 (选做)"""
    import akshare as ak
    import psycopg2
    import pandas as pd

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    total = 0
    failed = []

    for code in stock_codes:
        try:
            # 获取最新财务摘要
            df = ak.stock_financial_abstract(symbol=code)
            if df.empty:
                continue
            # 取最新一条
            latest = df.iloc[0]
            cur.execute(
                """INSERT INTO quant_raw_cn.fundamentals_snapshot
                (stock_code, report_date, eps, bvps, roe, operating_rev, net_profit, total_shares)
                VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s)
                ON CONFLICT (stock_code, report_date) DO NOTHING""",
                (
                    code,
                    float(latest.get("基本每股收益", 0) or 0),
                    float(latest.get("每股净资产", 0) or 0),
                    float(latest.get("净资产收益率", 0) or 0),
                    float(latest.get("营业收入", 0) or 0),
                    float(latest.get("净利润", 0) or 0),
                    float(latest.get("总股本", 0) or 0),
                ),
            )
            conn.commit()
            total += 1
            time.sleep(0.3)
        except Exception as e:
            conn.rollback()
            failed.append(code)
            logger.debug(f"基本面 {code}: {e}")

    cur.close()
    conn.close()
    logger.info(f"基本面: 同步 {total} 只, 失败 {len(failed)}")
    return {"total": total, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="A 股数据同步 (AKShare → PG)")
    parser.add_argument("--stocks", type=str, help="股票代码列表，逗号分隔")
    parser.add_argument(
        "--index",
        type=str,
        default="CSI300",
        choices=["CSI300", "CSI500", "SZ50"],
        help="指数成分股",
    )
    parser.add_argument("--days-back", type=int, default=365, help="回溯天数")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有数据")
    parser.add_argument("--fundamentals", action="store_true", help="同时同步基本面")
    parser.add_argument("--batch", type=int, default=5, help="批量大小")

    args = parser.parse_args()

    # 确定股票列表
    if args.stocks:
        codes = [s.strip().zfill(6) for s in args.stocks.split(",")]
    elif args.index == "CSI300":
        codes = _get_csi300_constituents()
    else:
        codes = CSI300_TOP20

    logger.info(f"开始同步 {len(codes)} 只股票，回溯 {args.days_back} 天")

    # 日线
    result = sync_daily(codes, args.days_back, args.batch, args.force)

    # 基本面
    if args.fundamentals:
        sync_fundamentals(codes)

    # 写 sync_log
    import psycopg2

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO quant_raw_cn.sync_log (source, status, records, duration_s, message) "
        "VALUES ('akshare_daily', 'success', %s, %s, %s)",
        (
            result["inserted"],
            result["duration_s"],
            f"total={result['total']}, failed={len(result['failed'])}",
        ),
    )
    conn.commit()
    cur.close()
    conn.close()

    print(f"\n{'=' * 50}")
    print(f"  同步完成: {result['inserted']}/{result['total']} 条新增")
    print(f"  耗时: {result['duration_s']:.1f}s")
    if result["failed"]:
        print(f"  失败: {result['failed']}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
