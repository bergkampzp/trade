# ruff: noqa: S101
"""Tests for backtest_to_pg.py — parse freqtrade backtest JSON + write NAV rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import backtest_to_pg as b2p  # noqa: E402


@pytest.fixture
def sample_backtest_json(tmp_path: Path) -> Path:
    payload = {
        "strategy": {
            "FactorSignalStrategy": {
                "starting_balance": 10000,
                "final_balance": 10030,
                "sharpe": 1.23,
                "max_drawdown_account": 0.05,
                "profit_total": 0.003,
                "daily_profit": [
                    ["2026-01-01", 10.0],
                    ["2026-01-02", -5.0],
                    ["2026-01-03", 25.0],
                ],
            }
        }
    }
    p = tmp_path / "bt.json"
    p.write_text(json.dumps(payload))
    return p


def test_parse_backtest_returns_nav_rows(sample_backtest_json):
    run_id, rows, summary = b2p.parse_backtest(sample_backtest_json, run_id="2026-01-01_abc")

    assert run_id == "2026-01-01_abc"
    # Each row: (run_id, date, nav, sharpe, max_drawdown, total_profit_pct)
    assert len(rows) == 3
    assert rows[0][0] == "2026-01-01_abc"
    assert rows[0][1] == "2026-01-01"
    assert rows[0][2] == 10010.0  # 10000 + 10
    assert rows[1][2] == 10005.0  # 10010 - 5
    assert rows[2][2] == 10030.0  # 10005 + 25

    # Sharpe / drawdown / total profit replicated on every row (they're run-level)
    assert all(r[3] == 1.23 for r in rows)
    assert all(r[4] == 0.05 for r in rows)
    assert all(abs(r[5] - 0.3) < 1e-9 for r in rows)  # profit_total * 100

    assert summary["starting_balance"] == 10000
    assert summary["final_balance"] == 10030


def test_parse_backtest_derives_run_id_from_filename(sample_backtest_json):
    run_id, _, _ = b2p.parse_backtest(sample_backtest_json)
    assert run_id == sample_backtest_json.stem


def test_parse_backtest_empty_daily_profit_raises(tmp_path):
    payload = {
        "strategy": {
            "Foo": {
                "starting_balance": 10000,
                "final_balance": 10000,
                "sharpe": 0,
                "max_drawdown_account": 0,
                "profit_total": 0,
                "daily_profit": [],
            }
        }
    }
    p = tmp_path / "empty.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="daily_profit"):
        b2p.parse_backtest(p)


def test_write_nav_rows_upserts(monkeypatch, sample_backtest_json):
    """write_nav_rows should DELETE run_id then INSERT new rows in one tx."""
    executed = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def execute(self, sql, params=None):
            executed.append(("execute", sql.strip().split()[0].upper(), params))

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append(("commit", None, None))

    def fake_execute_values(cur, sql, rows, page_size=1000):
        executed.append(("execute_values", sql.strip().split()[0].upper(), len(rows)))

    def fake_connect(dsn):
        executed.append(("connect", dsn, None))
        return FakeConn()

    monkeypatch.setattr(b2p.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(b2p, "execute_values", fake_execute_values)

    _, rows, _ = b2p.parse_backtest(sample_backtest_json, run_id="run-1")
    b2p.write_nav_rows("fake-dsn", rows)

    ops = [e[0] for e in executed]
    assert ops == ["connect", "execute", "execute_values", "commit"]
    # First execute is DELETE
    assert executed[1][1] == "DELETE"
    # execute_values is INSERT with 3 rows
    assert executed[2][1] == "INSERT"
    assert executed[2][2] == 3
