# Quant Dashboard Backend API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/api/v1/quant/*` endpoints to freqtrade's FastAPI server that serve factor scoreboard, OHLCV, z-score time series, IC rolling, correlation matrix, trade markers, and NAV curves from PostgreSQL — enabling the Quant Dashboard Vue.js SPA.

**Architecture:** New FastAPI router (`api_quant.py`) registered in freqtrade's `webserver.py`, backed by a `psycopg2.pool.ThreadedConnectionPool` connection to PostgreSQL (port 5433). Pydantic schemas in `api_quant_schemas.py`. Follows the same auth + webserver-mode dependency pattern as `api_backtest.py`.

**Tech Stack:** Python 3.12, FastAPI, psycopg2, Pydantic v2, pytest + TestClient

**Quick Start:** Use `../../scripts/start-quant-platform.sh api-start` to launch the API server.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `freqtrade/rpc/api_server/quant_db.py` | PostgreSQL connection pool + `query_rows(sql, params)` helper |
| `freqtrade/rpc/api_server/api_quant_schemas.py` | Pydantic response models for all `/quant/*` endpoints |
| `freqtrade/rpc/api_server/api_quant.py` | FastAPI router with all `/quant/*` route handlers |
| `freqtrade/rpc/api_server/webserver.py` | Modified: register the new quant router |
| `freqtrade/rpc/api_server/deps.py` | Modified: add `get_quant_db()` dependency |
| `tests/rpc/test_api_quant.py` | Tests for all quant endpoints |

All paths are relative to the worktree root: `/home/zp/work/trade/freqtrade/.worktrees/quant-mvp/`

---

### Task 1: PostgreSQL Connection Pool (`quant_db.py`)

**Files:**
- Create: `freqtrade/rpc/api_server/quant_db.py`
- Test: `tests/rpc/test_api_quant.py`

- [ ] **Step 1: Write the test**

```python
# tests/rpc/test_api_quant.py
"""Tests for the Quant Dashboard API endpoints."""

from unittest.mock import MagicMock, patch

import pytest

from freqtrade.rpc.api_server.quant_db import QuantDB


class TestQuantDB:
    def test_query_rows_returns_list_of_dicts(self):
        """query_rows should return a list of dicts with column names as keys."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.description = [("pair",), ("row_count",)]
        mock_cursor.fetchall.return_value = [("BTC/USDT", 26284), ("ETH/USDT", 8763)]

        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn

        db = QuantDB.__new__(QuantDB)
        db._pool = mock_pool

        result = db.query_rows("SELECT pair, COUNT(*) as row_count FROM t", ())
        assert result == [
            {"pair": "BTC/USDT", "row_count": 26284},
            {"pair": "ETH/USDT", "row_count": 8763},
        ]
        mock_pool.putconn.assert_called_once_with(mock_conn)

    def test_query_rows_returns_empty_on_no_results(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.description = [("pair",)]
        mock_cursor.fetchall.return_value = []

        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn

        db = QuantDB.__new__(QuantDB)
        db._pool = mock_pool

        result = db.query_rows("SELECT pair FROM t WHERE 1=0", ())
        assert result == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestQuantDB -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'freqtrade.rpc.api_server.quant_db'`

- [ ] **Step 3: Implement `quant_db.py`**

```python
# freqtrade/rpc/api_server/quant_db.py
"""PostgreSQL connection pool for the Quant Dashboard API."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2
import psycopg2.pool


logger = logging.getLogger(__name__)


class QuantDB:
    """Thin wrapper around a psycopg2 ThreadedConnectionPool."""

    def __init__(self, dsn: str, minconn: int = 1, maxconn: int = 4) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn)
        logger.info("QuantDB: connection pool created (%s)", dsn.split("password")[0])

    def query_rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a read-only query and return rows as list of dicts."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        self._pool.closeall()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestQuantDB -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/quant_db.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add QuantDB connection pool for PostgreSQL"
```

---

### Task 2: Pydantic Response Schemas (`api_quant_schemas.py`)

**Files:**
- Create: `freqtrade/rpc/api_server/api_quant_schemas.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
from freqtrade.rpc.api_server.api_quant_schemas import (
    DataSourcePair,
    DataSourceGroup,
    DataSourcesResponse,
    FactorMetrics,
    FactorSummary,
    FactorsResponse,
    TimeSeriesResponse,
    CorrelationMatrixResponse,
    TradeMarker,
    TradesResponse,
)


class TestQuantSchemas:
    def test_data_source_pair_serialization(self):
        p = DataSourcePair(
            pair="BTC/USDT",
            row_count=26284,
            date_min="2023-04-01T00:00:00Z",
            date_max="2026-04-10T00:00:00Z",
        )
        d = p.model_dump()
        assert d["pair"] == "BTC/USDT"
        assert d["row_count"] == 26284

    def test_factor_summary_serialization(self):
        f = FactorSummary(
            name="momentum_24h",
            bucket="A",
            direction="positive",
            description="24h trailing return",
            zscore_column="z_mom24",
            metrics=FactorMetrics(
                ic_mean=0.008,
                ic_ir=0.45,
                quantile_sharpe=1.2,
                backtest_sharpe=1.1,
                backtest_max_dd=0.12,
            ),
            verdict="PASS",
        )
        d = f.model_dump()
        assert d["name"] == "momentum_24h"
        assert d["metrics"]["ic_mean"] == 0.008
        assert d["verdict"] == "PASS"

    def test_time_series_response(self):
        ts = TimeSeriesResponse(
            columns=["date", "value"],
            data=[["2025-01-01T00:00:00Z", 1.23]],
        )
        assert len(ts.data) == 1

    def test_correlation_matrix_response(self):
        cm = CorrelationMatrixResponse(
            factors=["momentum_24h", "lowvol_24h"],
            matrix=[[1.0, 0.15], [0.15, 1.0]],
        )
        assert cm.matrix[0][1] == 0.15
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestQuantSchemas -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `api_quant_schemas.py`**

```python
# freqtrade/rpc/api_server/api_quant_schemas.py
"""Pydantic schemas for the Quant Dashboard API."""

from __future__ import annotations

from pydantic import BaseModel


# --- Data Sources ---

class DataSourcePair(BaseModel):
    pair: str
    row_count: int
    date_min: str | None = None
    date_max: str | None = None


class DataSourceGroup(BaseModel):
    name: str
    status: str  # "active" | "coming_soon"
    pairs: list[DataSourcePair]


class DataSourcesResponse(BaseModel):
    sources: list[DataSourceGroup]


# --- Factors ---

class FactorMetrics(BaseModel):
    ic_mean: float | None = None
    ic_ir: float | None = None
    quantile_sharpe: float | None = None
    backtest_sharpe: float | None = None
    backtest_max_dd: float | None = None


class FactorSummary(BaseModel):
    name: str
    bucket: str
    direction: str
    description: str
    zscore_column: str
    metrics: FactorMetrics
    verdict: str | None = None


class FactorsResponse(BaseModel):
    factors: list[FactorSummary]


class IcWindowStats(BaseModel):
    window: str
    ic_mean: float | None = None
    ic_std: float | None = None
    ic_ir: float | None = None
    ic_t_stat: float | None = None
    n_months: int | None = None


class QuantileBacktest(BaseModel):
    sharpe_annualized: float | None = None
    mean_ret_per_hour: float | None = None
    std_ret_per_hour: float | None = None
    total_return: float | None = None
    n_hours: int | None = None


class CorrelationEntry(BaseModel):
    factor_b: str
    corr_pearson: float
    n_obs: int | None = None


class FactorDetailResponse(BaseModel):
    name: str
    bucket: str
    direction: str
    description: str
    ic_by_window: list[IcWindowStats]
    quantile_backtest: QuantileBacktest | None = None
    correlations: list[CorrelationEntry]


# --- Time Series ---

class TimeSeriesResponse(BaseModel):
    columns: list[str]
    data: list[list]


# --- Correlation Matrix ---

class CorrelationMatrixResponse(BaseModel):
    factors: list[str]
    matrix: list[list[float]]


# --- Trades ---

class TradeMarker(BaseModel):
    open_date: str
    close_date: str | None = None
    open_rate: float
    close_rate: float | None = None
    profit_pct: float | None = None
    exit_reason: str | None = None
    direction: str = "long"


class TradesResponse(BaseModel):
    trades: list[TradeMarker]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestQuantSchemas -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/api_quant_schemas.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add Pydantic schemas for quant dashboard endpoints"
```

---

### Task 3: Dependency injection (`deps.py`) + Router registration (`webserver.py`)

**Files:**
- Modify: `freqtrade/rpc/api_server/deps.py`
- Modify: `freqtrade/rpc/api_server/webserver.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
from freqtrade.rpc.api_server.deps import get_quant_db


class TestQuantDeps:
    def test_get_quant_db_returns_none_without_config(self):
        """Without quant_db config, returns None."""
        result = get_quant_db(config={})
        assert result is None

    def test_get_quant_db_returns_none_without_dsn(self):
        result = get_quant_db(config={"quant_db": {}})
        assert result is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestQuantDeps -v
```
Expected: FAIL with `ImportError: cannot import name 'get_quant_db'`

- [ ] **Step 3: Add `get_quant_db()` to `deps.py`**

Add at the end of `freqtrade/rpc/api_server/deps.py`:

```python
def get_quant_db(config=Depends(get_config)):
    """Lazily create and cache a QuantDB connection pool."""
    quant_cfg = config.get("quant_db", {})
    dsn = quant_cfg.get("dsn")
    if not dsn:
        return None
    if not hasattr(get_quant_db, "_instance"):
        from freqtrade.rpc.api_server.quant_db import QuantDB

        get_quant_db._instance = QuantDB(dsn)
    return get_quant_db._instance
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestQuantDeps -v
```
Expected: 2 passed

- [ ] **Step 5: Register the quant router in `webserver.py`**

In `freqtrade/rpc/api_server/webserver.py`, inside the `configure_app` method, add after the `api_download_data` router registration (line ~163) and before the WebSocket router:

```python
        from freqtrade.rpc.api_server.api_quant import router as api_quant

        app.include_router(
            api_quant,
            prefix="/api/v1",
            dependencies=[Depends(http_basic_or_jwt_token), Depends(is_webserver_mode)],
        )
```

- [ ] **Step 6: Create a minimal `api_quant.py` stub so the import doesn't fail**

```python
# freqtrade/rpc/api_server/api_quant.py
"""Quant Dashboard API — factor research endpoints."""

import logging

from fastapi import APIRouter


logger = logging.getLogger(__name__)

router = APIRouter(tags=["quant"])
```

- [ ] **Step 7: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/deps.py freqtrade/rpc/api_server/webserver.py freqtrade/rpc/api_server/api_quant.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): register quant router and add get_quant_db dependency"
```

---

### Task 4: `GET /quant/data-sources` endpoint

**Files:**
- Modify: `freqtrade/rpc/api_server/api_quant.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
from freqtrade.rpc.api_server.api_quant import _get_data_sources
from freqtrade.rpc.api_server.api_quant_schemas import DataSourcesResponse


class TestDataSourcesEndpoint:
    def test_get_data_sources_with_data(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"pair": "BTC/USDT", "row_count": 26284,
             "date_min": "2023-04-01 00:00:00+00", "date_max": "2026-04-10 00:00:00+00"},
            {"pair": "ETH/USDT", "row_count": 8763,
             "date_min": "2025-04-11 00:00:00+00", "date_max": "2026-04-10 00:00:00+00"},
        ]
        result = _get_data_sources(mock_db)
        assert isinstance(result, DataSourcesResponse)
        crypto = next(s for s in result.sources if s.name == "Crypto")
        assert crypto.status == "active"
        assert len(crypto.pairs) == 2
        assert crypto.pairs[0].pair == "BTC/USDT"
        assert crypto.pairs[0].row_count == 26284

    def test_get_data_sources_without_db(self):
        result = _get_data_sources(None)
        assert isinstance(result, DataSourcesResponse)
        crypto = next(s for s in result.sources if s.name == "Crypto")
        assert crypto.pairs == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestDataSourcesEndpoint -v
```
Expected: FAIL with `ImportError: cannot import name '_get_data_sources'`

- [ ] **Step 3: Implement the endpoint in `api_quant.py`**

Replace the content of `freqtrade/rpc/api_server/api_quant.py`:

```python
# freqtrade/rpc/api_server/api_quant.py
"""Quant Dashboard API — factor research endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import HTTPException

from freqtrade.rpc.api_server.api_quant_schemas import (
    DataSourceGroup,
    DataSourcePair,
    DataSourcesResponse,
)
from freqtrade.rpc.api_server.deps import get_quant_db
from freqtrade.rpc.api_server.quant_db import QuantDB


logger = logging.getLogger(__name__)

router = APIRouter(tags=["quant"])

_DATA_SOURCES_SQL = """
    SELECT pair, COUNT(*) as row_count,
           MIN(date)::text as date_min, MAX(date)::text as date_max
    FROM quant_raw.ohlcv_crypto
    GROUP BY pair
    ORDER BY pair
"""


def _get_data_sources(db: QuantDB | None) -> DataSourcesResponse:
    pairs: list[DataSourcePair] = []
    if db is not None:
        rows = db.query_rows(_DATA_SOURCES_SQL)
        pairs = [DataSourcePair(**r) for r in rows]
    return DataSourcesResponse(
        sources=[
            DataSourceGroup(name="Crypto", status="active", pairs=pairs),
            DataSourceGroup(name="US Stocks", status="coming_soon", pairs=[]),
            DataSourceGroup(name="A-Shares", status="coming_soon", pairs=[]),
        ]
    )


@router.get("/quant/data-sources", response_model=DataSourcesResponse)
def api_quant_data_sources(db=Depends(get_quant_db)):
    return _get_data_sources(db)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestDataSourcesEndpoint -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/api_quant.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add GET /quant/data-sources endpoint"
```

---

### Task 5: `GET /quant/factors` endpoint

**Files:**
- Modify: `freqtrade/rpc/api_server/api_quant.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
import yaml

from freqtrade.rpc.api_server.api_quant import _get_factors
from freqtrade.rpc.api_server.api_quant_schemas import FactorsResponse


class TestFactorsEndpoint:
    def test_get_factors_merges_yml_and_scoreboard(self, tmp_path):
        # Create a minimal factors.yml
        yml = tmp_path / "factors.yml"
        yml.write_text(yaml.dump({"factors": [
            {"name": "momentum_24h", "bucket": "A", "direction": "positive",
             "description": "test", "zscore_column": "z_mom24",
             "feature_model": "feat_momentum_24h", "raw_column": "momentum_24h"},
        ]}))

        mock_db = MagicMock()
        # Scoreboard row
        mock_db.query_rows.return_value = [
            {"factor_name": "momentum_24h", "ic_mean": 0.008, "ic_ir": 0.45,
             "quantile_sharpe": 1.2, "backtest_sharpe": 1.1, "backtest_max_dd": 0.12,
             "verdict": "PASS"},
        ]

        result = _get_factors(mock_db, factors_yml_path=str(yml))
        assert isinstance(result, FactorsResponse)
        assert len(result.factors) == 1
        f = result.factors[0]
        assert f.name == "momentum_24h"
        assert f.metrics.ic_mean == 0.008
        assert f.verdict == "PASS"

    def test_get_factors_without_db(self, tmp_path):
        yml = tmp_path / "factors.yml"
        yml.write_text(yaml.dump({"factors": [
            {"name": "rsi_14", "bucket": "A", "direction": "positive",
             "description": "RSI", "zscore_column": "z_rsi14",
             "feature_model": "feat_rsi_14", "raw_column": "rsi_14"},
        ]}))

        result = _get_factors(None, factors_yml_path=str(yml))
        assert len(result.factors) == 1
        assert result.factors[0].metrics.ic_mean is None
        assert result.factors[0].verdict is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestFactorsEndpoint -v
```
Expected: FAIL with `ImportError: cannot import name '_get_factors'`

- [ ] **Step 3: Implement the endpoint**

Add to `freqtrade/rpc/api_server/api_quant.py` — new imports and functions:

```python
# Add to imports at top
from pathlib import Path
import yaml  # type: ignore[import-untyped]

from freqtrade.rpc.api_server.api_quant_schemas import (
    # ... existing imports ...
    FactorMetrics,
    FactorSummary,
    FactorsResponse,
)

# Add constant
_DEFAULT_FACTORS_YML = str(
    Path(__file__).resolve().parents[2] / "user_data" / "factors.yml"
)

_SCOREBOARD_SQL = """
    SELECT factor_name, ic_mean, ic_ir, quantile_sharpe,
           backtest_sharpe, backtest_max_dd, verdict
    FROM quant.mart_factor_scoreboard
    WHERE run_date = (SELECT MAX(run_date) FROM quant.mart_factor_scoreboard)
"""


def _get_factors(
    db: QuantDB | None, factors_yml_path: str = _DEFAULT_FACTORS_YML
) -> FactorsResponse:
    with open(factors_yml_path) as f:
        registry = yaml.safe_load(f).get("factors", [])

    scoreboard: dict[str, dict] = {}
    if db is not None:
        for row in db.query_rows(_SCOREBOARD_SQL):
            scoreboard[row["factor_name"]] = row

    factors = []
    for entry in registry:
        sb = scoreboard.get(entry["name"], {})
        factors.append(
            FactorSummary(
                name=entry["name"],
                bucket=entry["bucket"],
                direction=entry["direction"],
                description=entry["description"],
                zscore_column=entry["zscore_column"],
                metrics=FactorMetrics(
                    ic_mean=sb.get("ic_mean"),
                    ic_ir=sb.get("ic_ir"),
                    quantile_sharpe=sb.get("quantile_sharpe"),
                    backtest_sharpe=sb.get("backtest_sharpe"),
                    backtest_max_dd=sb.get("backtest_max_dd"),
                ),
                verdict=sb.get("verdict"),
            )
        )
    return FactorsResponse(factors=factors)


@router.get("/quant/factors", response_model=FactorsResponse)
def api_quant_factors(db=Depends(get_quant_db)):
    return _get_factors(db)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestFactorsEndpoint -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/api_quant.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add GET /quant/factors endpoint with scoreboard merge"
```

---

### Task 6: `GET /quant/factors/{name}` detail endpoint

**Files:**
- Modify: `freqtrade/rpc/api_server/api_quant.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
from freqtrade.rpc.api_server.api_quant import _get_factor_detail
from freqtrade.rpc.api_server.api_quant_schemas import FactorDetailResponse


class TestFactorDetailEndpoint:
    def test_get_factor_detail(self, tmp_path):
        yml = tmp_path / "factors.yml"
        yml.write_text(yaml.dump({"factors": [
            {"name": "momentum_24h", "bucket": "A", "direction": "positive",
             "description": "test", "zscore_column": "z_mom24",
             "feature_model": "feat_momentum_24h", "raw_column": "momentum_24h"},
        ]}))

        mock_db = MagicMock()
        # IC extended rows
        mock_db.query_rows.side_effect = [
            # IC by window
            [{"window_label": "overall", "ic_mean": 0.008, "ic_std": 0.02,
              "ic_ir": 0.4, "ic_t_stat": 2.1, "n_months": 12}],
            # Quantile backtest
            [{"sharpe_annualized": 1.2, "mean_ret_per_hour": 0.00002,
              "std_ret_per_hour": 0.001, "total_return": 0.12, "n_hours": 8760}],
            # Correlations
            [{"factor_b": "lowvol_24h", "corr_pearson": 0.15, "n_obs": 50000}],
        ]

        result = _get_factor_detail("momentum_24h", mock_db, factors_yml_path=str(yml))
        assert isinstance(result, FactorDetailResponse)
        assert result.name == "momentum_24h"
        assert len(result.ic_by_window) == 1
        assert result.ic_by_window[0].ic_mean == 0.008
        assert result.quantile_backtest.sharpe_annualized == 1.2
        assert len(result.correlations) == 1

    def test_get_factor_detail_unknown_factor(self, tmp_path):
        yml = tmp_path / "factors.yml"
        yml.write_text(yaml.dump({"factors": []}))
        mock_db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            _get_factor_detail("unknown", mock_db, factors_yml_path=str(yml))
        assert exc_info.value.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestFactorDetailEndpoint -v
```
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement the endpoint**

Add to `freqtrade/rpc/api_server/api_quant.py`:

```python
# Add to imports
from freqtrade.rpc.api_server.api_quant_schemas import (
    # ... existing ...
    CorrelationEntry,
    FactorDetailResponse,
    IcWindowStats,
    QuantileBacktest,
)

_IC_EXTENDED_SQL = """
    SELECT window_label, ic_mean, ic_std, ic_ir, ic_t_stat, n_months
    FROM quant.mart_factor_ic_extended
    WHERE factor_name = %s
    ORDER BY CASE window_label
        WHEN 'overall' THEN 0 WHEN 'last_12m' THEN 1 WHEN 'last_6m' THEN 2
    END
"""

_QUANTILE_BT_SQL = """
    SELECT sharpe_annualized, mean_ret_per_hour, std_ret_per_hour,
           total_return, n_hours
    FROM quant.mart_factor_quantile_backtest
    WHERE factor_name = %s
"""

_CORRELATION_SQL = """
    SELECT
        CASE WHEN factor_a = %s THEN factor_b ELSE factor_a END AS factor_b,
        corr_pearson, n_obs
    FROM quant.mart_factor_correlation
    WHERE (factor_a = %s OR factor_b = %s) AND factor_a <> factor_b
    ORDER BY ABS(corr_pearson) DESC
"""


def _get_factor_detail(
    name: str,
    db: QuantDB | None,
    factors_yml_path: str = _DEFAULT_FACTORS_YML,
) -> FactorDetailResponse:
    with open(factors_yml_path) as f:
        registry = yaml.safe_load(f).get("factors", [])
    entry = next((e for e in registry if e["name"] == name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Factor '{name}' not found in registry")

    ic_windows: list[IcWindowStats] = []
    qbt: QuantileBacktest | None = None
    corrs: list[CorrelationEntry] = []

    if db is not None:
        for row in db.query_rows(_IC_EXTENDED_SQL, (name,)):
            ic_windows.append(IcWindowStats(window=row["window_label"], **{
                k: row[k] for k in ("ic_mean", "ic_std", "ic_ir", "ic_t_stat", "n_months")
            }))

        qbt_rows = db.query_rows(_QUANTILE_BT_SQL, (name,))
        if qbt_rows:
            qbt = QuantileBacktest(**qbt_rows[0])

        for row in db.query_rows(_CORRELATION_SQL, (name, name, name)):
            corrs.append(CorrelationEntry(**row))

    return FactorDetailResponse(
        name=entry["name"],
        bucket=entry["bucket"],
        direction=entry["direction"],
        description=entry["description"],
        ic_by_window=ic_windows,
        quantile_backtest=qbt,
        correlations=corrs,
    )


@router.get("/quant/factors/{name}", response_model=FactorDetailResponse)
def api_quant_factor_detail(name: str, db=Depends(get_quant_db)):
    return _get_factor_detail(name, db)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestFactorDetailEndpoint -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/api_quant.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add GET /quant/factors/{name} detail endpoint"
```

---

### Task 7: `GET /quant/ohlcv` and `GET /quant/factor-zscore` endpoints

**Files:**
- Modify: `freqtrade/rpc/api_server/api_quant.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
from freqtrade.rpc.api_server.api_quant import _get_ohlcv, _get_factor_zscore
from freqtrade.rpc.api_server.api_quant_schemas import TimeSeriesResponse


class TestTimeSeriesEndpoints:
    def test_get_ohlcv(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"date": "2025-01-01 00:00:00+00", "open": 42000.0, "high": 42500.0,
             "low": 41800.0, "close": 42300.0, "volume": 100.5},
        ]
        result = _get_ohlcv(mock_db, "BTC/USDT", "20250101", "20250102")
        assert isinstance(result, TimeSeriesResponse)
        assert result.columns == ["date", "open", "high", "low", "close", "volume"]
        assert len(result.data) == 1
        assert result.data[0][0] == "2025-01-01 00:00:00+00"

    def test_get_ohlcv_no_db(self):
        with pytest.raises(HTTPException) as exc_info:
            _get_ohlcv(None, "BTC/USDT", "20250101", "20250102")
        assert exc_info.value.status_code == 503

    def test_get_factor_zscore(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"date": "2025-01-01 00:00:00+00", "zscore": 1.23},
            {"date": "2025-01-01 01:00:00+00", "zscore": -0.45},
        ]
        result = _get_factor_zscore(mock_db, "BTC/USDT", "momentum_24h", "20250101", "20250102")
        assert isinstance(result, TimeSeriesResponse)
        assert result.columns == ["date", "zscore"]
        assert len(result.data) == 2

    def test_get_factor_zscore_no_db(self):
        with pytest.raises(HTTPException) as exc_info:
            _get_factor_zscore(None, "BTC/USDT", "momentum_24h", "20250101", "20250102")
        assert exc_info.value.status_code == 503
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestTimeSeriesEndpoints -v
```
Expected: FAIL

- [ ] **Step 3: Implement the endpoints**

Add to `freqtrade/rpc/api_server/api_quant.py`:

```python
# Add to imports
from freqtrade.rpc.api_server.api_quant_schemas import (
    # ... existing ...
    TimeSeriesResponse,
)

_OHLCV_SQL = """
    SELECT date::text, open, high, low, close, volume
    FROM quant_raw.ohlcv_crypto
    WHERE pair = %s AND date >= %s::timestamp AND date < %s::timestamp
    ORDER BY date
"""

_FACTOR_ZSCORE_SQL = """
    SELECT date::text, zscore
    FROM quant.mart_factor_values_long
    WHERE pair = %s AND factor_name = %s
      AND date >= %s::timestamp AND date < %s::timestamp
    ORDER BY date
"""


def _require_db(db: QuantDB | None) -> QuantDB:
    if db is None:
        raise HTTPException(status_code=503, detail="PostgreSQL (quant_db) not configured")
    return db


def _parse_timerange(tr: str) -> tuple[str, str]:
    """Convert '20250101-20250401' to ('2025-01-01', '2025-04-01')."""
    parts = tr.split("-")
    def fmt(s: str) -> str:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return fmt(parts[0]), fmt(parts[1])


def _get_ohlcv(
    db: QuantDB | None, pair: str, start: str, end: str
) -> TimeSeriesResponse:
    db = _require_db(db)
    start_d, end_d = _parse_timerange(f"{start}-{end}")
    rows = db.query_rows(_OHLCV_SQL, (pair, start_d, end_d))
    columns = ["date", "open", "high", "low", "close", "volume"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


def _get_factor_zscore(
    db: QuantDB | None, pair: str, factor: str, start: str, end: str
) -> TimeSeriesResponse:
    db = _require_db(db)
    start_d, end_d = _parse_timerange(f"{start}-{end}")
    rows = db.query_rows(_FACTOR_ZSCORE_SQL, (pair, factor, start_d, end_d))
    columns = ["date", "zscore"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


@router.get("/quant/ohlcv", response_model=TimeSeriesResponse)
def api_quant_ohlcv(
    pair: str,
    start: Annotated[str, Query(pattern=r"^\d{8}$")],
    end: Annotated[str, Query(pattern=r"^\d{8}$")],
    db=Depends(get_quant_db),
):
    return _get_ohlcv(db, pair, start, end)


@router.get("/quant/factor-zscore", response_model=TimeSeriesResponse)
def api_quant_factor_zscore(
    pair: str,
    factor: str,
    start: Annotated[str, Query(pattern=r"^\d{8}$")],
    end: Annotated[str, Query(pattern=r"^\d{8}$")],
    db=Depends(get_quant_db),
):
    return _get_factor_zscore(db, pair, factor, start, end)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestTimeSeriesEndpoints -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/api_quant.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add GET /quant/ohlcv and /quant/factor-zscore endpoints"
```

---

### Task 8: `GET /quant/ic-rolling`, `/quant/factor-correlation`, `/quant/nav` endpoints

**Files:**
- Modify: `freqtrade/rpc/api_server/api_quant.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
from freqtrade.rpc.api_server.api_quant import (
    _get_ic_rolling,
    _get_factor_correlation,
    _get_nav,
)
from freqtrade.rpc.api_server.api_quant_schemas import CorrelationMatrixResponse


class TestRemainingEndpoints:
    def test_get_ic_rolling(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"month": "2025-01", "monthly_ic": 0.05, "rolling_3m_ic": 0.04,
             "rolling_3m_ic_std": 0.02},
        ]
        result = _get_ic_rolling(mock_db, "momentum_24h")
        assert isinstance(result, TimeSeriesResponse)
        assert result.columns == ["month", "monthly_ic", "rolling_3m_ic", "rolling_3m_ic_std"]
        assert len(result.data) == 1

    def test_get_factor_correlation(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"factor_a": "lowvol_24h", "factor_b": "momentum_24h", "corr_pearson": 0.15},
            {"factor_a": "momentum_24h", "factor_b": "momentum_24h", "corr_pearson": 1.0},
            {"factor_a": "lowvol_24h", "factor_b": "lowvol_24h", "corr_pearson": 1.0},
        ]
        result = _get_factor_correlation(mock_db)
        assert isinstance(result, CorrelationMatrixResponse)
        assert len(result.factors) >= 2

    def test_get_nav(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"date": "2025-01-01", "nav": 10000.0},
            {"date": "2025-01-02", "nav": 10050.0},
        ]
        result = _get_nav(mock_db, "momentum_24h")
        assert isinstance(result, TimeSeriesResponse)
        assert result.columns == ["date", "nav"]
        assert len(result.data) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestRemainingEndpoints -v
```
Expected: FAIL

- [ ] **Step 3: Implement the endpoints**

Add to `freqtrade/rpc/api_server/api_quant.py`:

```python
# Add to imports
from freqtrade.rpc.api_server.api_quant_schemas import (
    # ... existing ...
    CorrelationMatrixResponse,
)

_IC_ROLLING_SQL = """
    SELECT TO_CHAR(month, 'YYYY-MM') AS month,
           monthly_ic, rolling_3m_ic, rolling_3m_ic_std
    FROM quant.mart_factor_ic_rolling
    WHERE factor_name = %s
    ORDER BY month
"""

_CORR_MATRIX_SQL = """
    SELECT factor_a, factor_b, corr_pearson
    FROM quant.mart_factor_correlation
    UNION ALL
    SELECT factor_b, factor_a, corr_pearson
    FROM quant.mart_factor_correlation
    WHERE factor_a <> factor_b
    ORDER BY 1, 2
"""

_NAV_SQL = """
    SELECT date::text, nav
    FROM quant.mart_backtest_nav
    WHERE run_id LIKE 'sprint2_' || %s || '%%'
    ORDER BY date
"""


def _get_ic_rolling(db: QuantDB | None, factor: str) -> TimeSeriesResponse:
    db = _require_db(db)
    rows = db.query_rows(_IC_ROLLING_SQL, (factor,))
    columns = ["month", "monthly_ic", "rolling_3m_ic", "rolling_3m_ic_std"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


def _get_factor_correlation(db: QuantDB | None) -> CorrelationMatrixResponse:
    db = _require_db(db)
    rows = db.query_rows(_CORR_MATRIX_SQL)
    # Build symmetric matrix
    factors_set: set[str] = set()
    corr_map: dict[tuple[str, str], float] = {}
    for r in rows:
        fa, fb = r["factor_a"], r["factor_b"]
        factors_set.add(fa)
        factors_set.add(fb)
        corr_map[(fa, fb)] = float(r["corr_pearson"])
    factors = sorted(factors_set)
    matrix = []
    for fa in factors:
        row = []
        for fb in factors:
            if fa == fb:
                row.append(1.0)
            else:
                row.append(corr_map.get((fa, fb), 0.0))
        matrix.append(row)
    return CorrelationMatrixResponse(factors=factors, matrix=matrix)


def _get_nav(db: QuantDB | None, factor: str) -> TimeSeriesResponse:
    db = _require_db(db)
    rows = db.query_rows(_NAV_SQL, (factor,))
    columns = ["date", "nav"]
    data = [[r[c] for c in columns] for r in rows]
    return TimeSeriesResponse(columns=columns, data=data)


@router.get("/quant/ic-rolling", response_model=TimeSeriesResponse)
def api_quant_ic_rolling(factor: str, db=Depends(get_quant_db)):
    return _get_ic_rolling(db, factor)


@router.get("/quant/factor-correlation", response_model=CorrelationMatrixResponse)
def api_quant_factor_correlation(db=Depends(get_quant_db)):
    return _get_factor_correlation(db)


@router.get("/quant/nav", response_model=TimeSeriesResponse)
def api_quant_nav(factor: str, db=Depends(get_quant_db)):
    return _get_nav(db, factor)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestRemainingEndpoints -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/api_quant.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add ic-rolling, factor-correlation, and nav endpoints"
```

---

### Task 9: `GET /quant/trades` endpoint

**Files:**
- Modify: `freqtrade/rpc/api_server/api_quant.py`
- Test: `tests/rpc/test_api_quant.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/rpc/test_api_quant.py`:

```python
from freqtrade.rpc.api_server.api_quant import _get_trades
from freqtrade.rpc.api_server.api_quant_schemas import TradesResponse


class TestTradesEndpoint:
    def test_get_trades(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"open_date": "2025-01-15 08:00:00+00", "close_date": "2025-01-15 14:00:00+00",
             "open_rate": 42150.0, "close_rate": 42380.0, "profit_pct": 0.54,
             "exit_reason": "roi", "direction": "long"},
        ]
        result = _get_trades(mock_db, "BTC/USDT", "momentum_24h")
        assert isinstance(result, TradesResponse)
        assert len(result.trades) == 1
        assert result.trades[0].open_rate == 42150.0

    def test_get_trades_no_db(self):
        with pytest.raises(HTTPException) as exc_info:
            _get_trades(None, "BTC/USDT", "momentum_24h")
        assert exc_info.value.status_code == 503
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestTradesEndpoint -v
```
Expected: FAIL

- [ ] **Step 3: Implement the endpoint**

Add to `freqtrade/rpc/api_server/api_quant.py`:

```python
# Add to imports
from freqtrade.rpc.api_server.api_quant_schemas import (
    # ... existing ...
    TradeMarker,
    TradesResponse,
)

_TRADES_SQL = """
    SELECT open_date::text, close_date::text, open_rate, close_rate,
           profit_pct, exit_reason, 'long' as direction
    FROM quant.mart_backtest_trades
    WHERE pair = %s AND run_id LIKE 'sprint2_' || %s || '%%'
    ORDER BY open_date
"""


def _get_trades(
    db: QuantDB | None, pair: str, factor: str
) -> TradesResponse:
    db = _require_db(db)
    rows = db.query_rows(_TRADES_SQL, (pair, factor))
    trades = [TradeMarker(**r) for r in rows]
    return TradesResponse(trades=trades)


@router.get("/quant/trades", response_model=TradesResponse)
def api_quant_trades(pair: str, factor: str, db=Depends(get_quant_db)):
    return _get_trades(db, pair, factor)
```

**Note:** The `quant.mart_backtest_trades` table may not exist yet — it needs to be created from freqtrade backtest results (similar to `mart_backtest_nav`). If this table is missing, the endpoint will return a SQL error at runtime. This can be addressed by either:
1. Creating a `ddl/004_quant_backtest_trades.sql` DDL
2. Or falling back to reading freqtrade's JSON backtest results directly

For now, the SQL pattern is correct and the test validates the logic.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py::TestTradesEndpoint -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add freqtrade/rpc/api_server/api_quant.py tests/rpc/test_api_quant.py
git commit -m "feat(quant-api): add GET /quant/trades endpoint for trade markers"
```

---

### Task 10: Config + Integration verification

**Files:**
- Modify: `user_data/config_crypto_mvp.json` — add `quant_db` and `api_server` sections

- [ ] **Step 1: Add config sections**

Read the current `user_data/config_crypto_mvp.json` and add:

```json
{
  "api_server": {
    "enabled": true,
    "listen_ip_address": "127.0.0.1",
    "listen_port": 8080,
    "username": "quant",
    "password": "quant123",
    "jwt_secret_key": "quant-dashboard-secret",
    "CORS_origins": ["http://localhost:5173"],
    "enable_openapi": true
  },
  "quant_db": {
    "dsn": "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"
  }
}
```

- [ ] **Step 2: Run all quant tests**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
python -m pytest tests/rpc/test_api_quant.py -v
```
Expected: All tests pass (14+ tests)

- [ ] **Step 3: Start webserver and test with curl**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
freqtrade webserver --config user_data/config_crypto_mvp.json &
sleep 3

# Get JWT token
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/token/login \
  -u quant:quant123 | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test data-sources
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/quant/data-sources | python3 -m json.tool

# Test factors
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/quant/factors | python3 -m json.tool

# Test OHLCV
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/v1/quant/ohlcv?pair=BTC/USDT&start=20250401&end=20250410" | python3 -m json.tool

# Test factor z-score
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/v1/quant/factor-zscore?pair=BTC/USDT&factor=momentum_24h&start=20250401&end=20250410" | python3 -m json.tool

# Cleanup
kill %1
```

Expected: All endpoints return valid JSON with data from PostgreSQL.

- [ ] **Step 4: Commit config**

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp
git add user_data/config_crypto_mvp.json
git commit -m "feat(quant-api): add api_server and quant_db config for dashboard"
```

---

## Verification Summary

1. **Unit tests**: `python -m pytest tests/rpc/test_api_quant.py -v` — all pass
2. **Swagger UI**: Start webserver, visit `http://localhost:8080/docs`, see all `/quant/*` endpoints listed
3. **Live queries**: Each endpoint returns real data from PostgreSQL quant schema
4. **Auth**: All endpoints require JWT token (return 401 without it)

## Endpoints Delivered

| Endpoint | Status |
|----------|--------|
| `GET /quant/data-sources` | Task 4 |
| `GET /quant/factors` | Task 5 |
| `GET /quant/factors/{name}` | Task 6 |
| `GET /quant/ohlcv` | Task 7 |
| `GET /quant/factor-zscore` | Task 7 |
| `GET /quant/ic-rolling` | Task 8 |
| `GET /quant/factor-correlation` | Task 8 |
| `GET /quant/nav` | Task 8 |
| `GET /quant/trades` | Task 9 |

---

## Quick Start Commands

### Start API Server

```bash
# From freqtrade root
cd /home/zp/work/trade/freqtrade

# Quick start (infra + api)
./scripts/quick-start.sh

# Or start API only
./scripts/start-quant-platform.sh api-start
```

### Test Endpoints

```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/token/login \
  -u quant:quant123 | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test endpoints
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/quant/data-sources
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/quant/factors
```

### Service Management

```bash
# Check status
./scripts/start-quant-platform.sh status

# Stop API
./scripts/start-quant-platform.sh api-stop

# Stop all services
./scripts/start-quant-platform.sh full-stop
```
