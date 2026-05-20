# ruff: noqa: S101
"""Tests for FactorSignalStrategy.

These tests exercise the strategy's deterministic logic (signal merge, entry/exit
rules) with a pre-loaded signals DataFrame. The DB-fetch path is covered by a
separate test that monkey-patches psycopg2, so the bulk of tests do not require
a running Postgres.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


# Make user_data/strategies importable
STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from factor_signal_strategy import FactorSignalStrategy  # noqa: E402


@pytest.fixture
def signals_df() -> pd.DataFrame:
    """A small mart_hourly_signals table covering two timestamps × 3 pairs."""
    return pd.DataFrame(
        [
            # t1: BTC rank 1 (strong entry), ETH rank 2 (strong entry), SOL rank 3 (weak score)
            {
                "pair": "BTC/USDT",
                "date": pd.Timestamp("2026-01-01 00:00", tz="UTC"),
                "composite_score": 1.2,
                "rank_in_date": 1,
            },
            {
                "pair": "ETH/USDT",
                "date": pd.Timestamp("2026-01-01 00:00", tz="UTC"),
                "composite_score": 0.8,
                "rank_in_date": 2,
            },
            {
                "pair": "SOL/USDT",
                "date": pd.Timestamp("2026-01-01 00:00", tz="UTC"),
                "composite_score": 0.3,
                "rank_in_date": 3,
            },
            # t2: BTC rank 6 (exit), ETH rank 3 (hold), SOL rank 1 (strong entry)
            {
                "pair": "BTC/USDT",
                "date": pd.Timestamp("2026-01-01 01:00", tz="UTC"),
                "composite_score": -0.2,
                "rank_in_date": 6,
            },
            {
                "pair": "ETH/USDT",
                "date": pd.Timestamp("2026-01-01 01:00", tz="UTC"),
                "composite_score": 0.4,
                "rank_in_date": 3,
            },
            {
                "pair": "SOL/USDT",
                "date": pd.Timestamp("2026-01-01 01:00", tz="UTC"),
                "composite_score": 0.9,
                "rank_in_date": 1,
            },
        ]
    )


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Minimal OHLCV dataframe (freqtrade-shaped) for BTC/USDT."""
    return pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2026-01-01 00:00", tz="UTC"),
                pd.Timestamp("2026-01-01 01:00", tz="UTC"),
            ],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000.0, 1100.0],
        }
    )


def _make_strategy(signals_df: pd.DataFrame) -> FactorSignalStrategy:
    """Construct strategy without hitting Postgres: inject signals directly."""
    # IStrategy.__init__ requires a config dict. Bypass it by using __new__ and
    # setting only the attributes the methods under test read.
    strat = FactorSignalStrategy.__new__(FactorSignalStrategy)
    strat._signals_df = signals_df
    return strat


def test_populate_indicators_merges_signals_by_date(signals_df, ohlcv_df):
    strat = _make_strategy(signals_df)
    out = strat.populate_indicators(ohlcv_df.copy(), {"pair": "BTC/USDT"})

    assert list(out["composite_score"]) == [1.2, -0.2]
    assert list(out["rank_in_date"]) == [1, 6]


def test_populate_indicators_missing_pair_fills_neutral(signals_df, ohlcv_df):
    strat = _make_strategy(signals_df)
    # Pair not in signals table → both columns should be NaN / sentinel
    out = strat.populate_indicators(ohlcv_df.copy(), {"pair": "DOGE/USDT"})

    assert out["composite_score"].isna().all()
    assert out["rank_in_date"].isna().all()


def test_populate_entry_trend_triggers_on_top_rank_and_strong_score(signals_df, ohlcv_df):
    strat = _make_strategy(signals_df)
    df = strat.populate_indicators(ohlcv_df.copy(), {"pair": "BTC/USDT"})
    df = strat.populate_entry_trend(df, {"pair": "BTC/USDT"})

    # t1: rank=1 score=1.2 → enter; t2: rank=6 score=-0.2 → no entry
    assert list(df["enter_long"]) == [1, 0]


def test_populate_entry_trend_score_below_threshold_no_entry(signals_df, ohlcv_df):
    strat = _make_strategy(signals_df)
    # SOL at t1: rank=3 (<=3) but score=0.3 (<0.5) → no entry
    # SOL at t2: rank=1 score=0.9 → entry
    sol_df = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2026-01-01 00:00", tz="UTC"),
                pd.Timestamp("2026-01-01 01:00", tz="UTC"),
            ],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 10.5],
            "volume": [500.0, 500.0],
        }
    )
    df = strat.populate_indicators(sol_df, {"pair": "SOL/USDT"})
    df = strat.populate_entry_trend(df, {"pair": "SOL/USDT"})

    assert list(df["enter_long"]) == [0, 1]


def test_populate_exit_trend_triggers_when_rank_falls(signals_df, ohlcv_df):
    strat = _make_strategy(signals_df)
    df = strat.populate_indicators(ohlcv_df.copy(), {"pair": "BTC/USDT"})
    df = strat.populate_exit_trend(df, {"pair": "BTC/USDT"})

    # t1: rank=1 → no exit; t2: rank=6 (>5) → exit
    assert list(df["exit_long"]) == [0, 1]


def test_populate_exit_trend_missing_pair_no_exit(signals_df, ohlcv_df):
    strat = _make_strategy(signals_df)
    df = strat.populate_indicators(ohlcv_df.copy(), {"pair": "DOGE/USDT"})
    df = strat.populate_exit_trend(df, {"pair": "DOGE/USDT"})

    # NaN rank should not trigger exit
    assert list(df["exit_long"]) == [0, 0]


def test_load_signals_from_pg_uses_psycopg2(monkeypatch, signals_df):
    """bot_start loads mart_hourly_signals via psycopg2 into self._signals_df."""
    import factor_signal_strategy as mod

    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def execute(self, sql):
            captured["sql"] = sql

        def fetchall(self):
            return [
                (row["pair"], row["date"], row["composite_score"], row["rank_in_date"])
                for _, row in signals_df.iterrows()
            ]

        description = [("pair",), ("date",), ("composite_score",), ("rank_in_date",)]

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    def fake_connect(dsn):
        captured["dsn"] = dsn
        return FakeConn()

    monkeypatch.setattr(mod.psycopg2, "connect", fake_connect)

    strat = FactorSignalStrategy.__new__(FactorSignalStrategy)
    strat.config = {}
    strat.bot_start()

    assert "mart_hourly_signals" in captured["sql"]
    assert len(strat._signals_df) == len(signals_df)
    assert set(strat._signals_df.columns) >= {"pair", "date", "composite_score", "rank_in_date"}
