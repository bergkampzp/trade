"""Sync freqtrade feather OHLCV files into warehouse.quant_raw.ohlcv_crypto.

Usage:
    python -m user_data.scripts.feather_to_pg
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "user_data" / "data" / "binance"
DEFAULT_PAIRS: list[str] = [
    "BTC_USDT",
    "ETH_USDT",
    "SOL_USDT",
    "BNB_USDT",
    "XRP_USDT",
    "ADA_USDT",
    "DOGE_USDT",
    "AVAX_USDT",
    "DOT_USDT",
    "LINK_USDT",
]
DEFAULT_TIMEFRAME = "1h"

PG_DSN = os.environ.get(
    "QUANT_PG_DSN",
    "host=localhost port=5433 dbname=warehouse user=postgres password=postgres",
)

UPSERT_SQL = """
INSERT INTO quant_raw.ohlcv_crypto
    (pair, timeframe, date, open, high, low, close, volume)
VALUES %s
ON CONFLICT (pair, timeframe, date) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    ingested_at = NOW()
"""


def _dataframe_to_rows(df: pd.DataFrame, pair: str, timeframe: str) -> list[tuple]:
    rows: list[tuple] = []
    for record in df.itertuples(index=False):
        rows.append(
            (
                pair,
                timeframe,
                record.date,
                float(record.open),
                float(record.high),
                float(record.low),
                float(record.close),
                float(record.volume),
            )
        )
    return rows


def sync_pair(
    conn,
    data_dir: Path,
    pair_file: str,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> int:
    """Sync one pair/timeframe feather file into Postgres. Returns rows written."""
    feather_path = data_dir / f"{pair_file}-{timeframe}.feather"
    if not feather_path.exists():
        raise FileNotFoundError(f"Feather file not found: {feather_path}")

    df = pd.read_feather(feather_path)
    pair = pair_file.replace("_", "/")
    rows = _dataframe_to_rows(df, pair=pair, timeframe=timeframe)

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=1000)
    conn.commit()

    logger.info("synced %s: %d rows", pair, len(rows))
    return len(rows)


def main(
    pairs: Sequence[str] = DEFAULT_PAIRS,
    timeframe: str = DEFAULT_TIMEFRAME,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    total = 0
    with psycopg2.connect(PG_DSN) as conn:
        for pair_file in pairs:
            total += sync_pair(conn, data_dir, pair_file, timeframe)
    logger.info("TOTAL rows synced: %d", total)
    return total


if __name__ == "__main__":
    main()
