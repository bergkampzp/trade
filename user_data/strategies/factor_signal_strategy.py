"""FactorSignalStrategy — consume pre-computed factor signals from Postgres.

Reads ``quant.mart_hourly_signals`` (produced by the dbt project at
``/home/zp/airbyte/quant_warehouse``) and trades the top-ranked pairs.

Entry: rank_in_date <= 3 AND composite_score > 0.5
Exit : rank_in_date >  5

Single-factor mode: set QUANT_FACTOR_NAME env var to a z-score column suffix
(e.g. "momentum_24h" → reads z_mom24 from factors.yml zscore_column mapping).
The orchestrator validates factor names against factors.yml before spawning.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
import yaml  # type: ignore[import-untyped]
from pandas import DataFrame

from freqtrade.strategy import IStrategy


logger = logging.getLogger(__name__)

DEFAULT_PG_DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"

# Default composite mode SQL
_COMPOSITE_SQL = """
    SELECT pair, date, composite_score, rank_in_date
    FROM quant.mart_hourly_signals
    ORDER BY date, rank_in_date
"""


def _load_factor_zscore_map() -> dict[str, str]:
    """Load factor_name → zscore_column mapping from factors.yml."""
    yml_path = Path(__file__).resolve().parents[1] / "factors.yml"
    if not yml_path.exists():
        return {}
    with yml_path.open() as f:
        data = yaml.safe_load(f)
    return {f["name"]: f["zscore_column"] for f in data.get("factors", [])}


def _build_signals_sql(factor_name: str | None) -> str:
    """Build the SQL for loading signals, supporting single-factor override."""
    if not factor_name:
        return _COMPOSITE_SQL

    zscore_map = _load_factor_zscore_map()
    if factor_name not in zscore_map:
        raise ValueError(
            f"QUANT_FACTOR_NAME={factor_name!r} not found in factors.yml. "
            f"Valid names: {sorted(zscore_map.keys())}"
        )
    zcol = zscore_map[factor_name]

    # Safe: zcol comes from a checked-in YAML file, not user input
    return f"""
        SELECT pair, date,
               {zcol} AS composite_score,
               RANK() OVER (
                   PARTITION BY date ORDER BY {zcol} DESC NULLS LAST
               ) AS rank_in_date
        FROM quant.mart_hourly_signals
        WHERE {zcol} IS NOT NULL
        ORDER BY date, rank_in_date
    """


class FactorSignalStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    stoploss = -0.05
    minimal_roi = {"0": 10.0}  # effectively no ROI target — exit via rank rule
    process_only_new_candles = True
    startup_candle_count: int = 0
    can_short = False

    # Populated by bot_start()
    _signals_df: pd.DataFrame | None = None

    # --- lifecycle -----------------------------------------------------------

    def bot_start(self, **kwargs: Any) -> None:
        """Load the full mart_hourly_signals table once at startup."""
        dsn = os.environ.get("QUANT_PG_DSN", DEFAULT_PG_DSN)
        factor_name = os.environ.get("QUANT_FACTOR_NAME")
        sql = _build_signals_sql(factor_name)
        mode = f"single-factor({factor_name})" if factor_name else "composite"
        logger.info("FactorSignalStrategy: loading signals [%s] from Postgres", mode)
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        df = pd.DataFrame(rows, columns=cols)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], utc=True)
            df["composite_score"] = df["composite_score"].astype(float)
            df["rank_in_date"] = df["rank_in_date"].astype("Int64")
        self._signals_df = df
        logger.info(
            "FactorSignalStrategy: loaded %d signal rows across %d pairs",
            len(df),
            df["pair"].nunique() if not df.empty else 0,
        )

    # --- indicators / signals ------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        signals = self._signals_df
        if signals is None or signals.empty:
            dataframe["composite_score"] = pd.NA
            dataframe["rank_in_date"] = pd.NA
            return dataframe

        pair_signals = signals.loc[
            signals["pair"] == pair, ["date", "composite_score", "rank_in_date"]
        ]
        merged = dataframe.merge(pair_signals, on="date", how="left")
        return merged

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        rank = dataframe["rank_in_date"]
        score = dataframe["composite_score"]
        cond = rank.notna() & score.notna() & (rank <= 3) & (score > 0.5)
        dataframe["enter_long"] = cond.astype(int)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        rank = dataframe["rank_in_date"]
        cond = rank.notna() & (rank > 5)
        dataframe["exit_long"] = cond.astype(int)
        return dataframe
