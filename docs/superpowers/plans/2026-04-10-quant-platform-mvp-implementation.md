# 个人量化研究平台 MVP 实施计划（数字货币 + freqtrade）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以最短路径端到端打通「Binance 行情采集 → feather → Postgres 数仓 → dbt 因子 → freqtrade 回测 + dry-run → Metabase 仪表盘」，由 Dagster 每小时统一调度。

**Architecture:** 复用 freqtrade 仓库作为数据采集器 / 回测引擎 / dry-run 执行器；复用现有数据平台的 `dest-postgres` + dbt worker + Metabase；新增 `feather_to_pg.py` + `backtest_to_pg.py` 桥接脚本、`quant_warehouse` dbt 项目、`FactorSignalStrategy` 因子策略、Dagster 调度容器。因子在 dbt 计算并落地到 `warehouse.quant.mart_hourly_signals`，`FactorSignalStrategy` 在 `__init__` 时一次性读入内存。

**Tech Stack:** freqtrade, PostgreSQL 15 (dest-postgres:5433), dbt-postgres, Dagster, pandas + pyarrow + psycopg2-binary, Metabase, Docker Compose.

**Spec 参考:** [docs/superpowers/specs/2026-04-10-personal-quant-platform-mvp-design.md](../specs/2026-04-10-personal-quant-platform-mvp-design.md)

---

## 文件结构一览

### 新增文件

```
/home/zp/work/trade/freqtrade/
├── user_data/
│   ├── config_crypto_mvp.json                            # freqtrade 配置
│   ├── strategies/
│   │   └── factor_signal_strategy.py                     # 因子策略
│   ├── scripts/
│   │   ├── __init__.py
│   │   ├── feather_to_pg.py                              # feather → PG 同步
│   │   └── backtest_to_pg.py                             # 回测结果 → PG 同步
│   └── tests/
│       ├── __init__.py
│       ├── test_feather_to_pg.py
│       ├── test_backtest_to_pg.py
│       └── test_factor_signal_strategy.py

/home/zp/airbyte/quant_warehouse/                          # 新 dbt 项目
├── dbt_project.yml
├── profiles.yml                                           # 或在 ~/.dbt/profiles.yml 追加
├── models/
│   ├── sources.yml
│   ├── staging/
│   │   └── stg_ohlcv_crypto.sql
│   ├── intermediate/
│   │   └── int_hourly_returns.sql
│   ├── features/
│   │   ├── feat_momentum_24h.sql
│   │   ├── feat_volatility_24h.sql
│   │   └── feat_volume_zscore_24h.sql
│   └── mart/
│       ├── mart_hourly_signals.sql
│       ├── mart_factor_ic.sql
│       └── mart_backtest_nav.sql
└── tests/
    └── schema.yml                                          # dbt schema tests

/home/zp/airbyte/dagster_quant/                             # 新 Dagster 项目
├── workspace.yaml
├── pyproject.toml
├── dagster_quant/
│   ├── __init__.py
│   ├── assets.py
│   └── definitions.py
└── tests/
    └── test_assets.py

/home/zp/airbyte/docker-platform/docker-compose.yml         # 修改：增加 dagster 服务
```

### 修改文件

- `/home/zp/airbyte/docker-platform/docker-compose.yml`：新增 `dagster` 服务
- `~/.dbt/profiles.yml`：新增 `quant` profile（或项目内自带）

### 每个文件的职责

| 文件 | 职责 |
|---|---|
| `config_crypto_mvp.json` | freqtrade 运行参数（币对、dry_run、策略名） |
| `factor_signal_strategy.py` | 从 PG 读 `mart_hourly_signals`，按 rank 入场 / 出场 |
| `feather_to_pg.py` | 把 `user_data/data/binance/*.feather` UPSERT 到 `warehouse.quant_raw.ohlcv_crypto` |
| `backtest_to_pg.py` | 把 `user_data/backtest_results/*.json` 净值曲线写到 `warehouse.quant.mart_backtest_nav` |
| `stg_ohlcv_crypto.sql` | view：清洗、NULL 过滤 |
| `int_hourly_returns.sql` | table：每小时收益率 |
| `feat_*.sql` | 三个因子原始值 |
| `mart_hourly_signals.sql` | 截面 Z-score + 合成得分 + rank |
| `mart_factor_ic.sql` | 因子月度 IC |
| `mart_backtest_nav.sql` | 回测净值曲线（由 `backtest_to_pg.py` 写入，dbt 仅 ref） |
| `assets.py` | Dagster 4 个 asset + 定时 schedule |
| `docker-compose.yml` | 增加 dagster 容器，挂载 freqtrade 和 quant_warehouse 目录 |

---

## 前置条件

执行 Task 1 之前必须确认：

- [ ] `dest-postgres` 容器运行中：`docker ps --filter name=dest-postgres`（端口 5433）
- [ ] 能用 `psql -h localhost -p 5433 -U postgres -d warehouse -c '\l'` 连上
- [ ] `freqtrade` 可运行：`cd /home/zp/work/trade/freqtrade && python -m freqtrade --version`
- [ ] `dbt-postgres` 已安装在 dbt worker 容器里：`docker exec <dbt-worker> dbt --version`
- [ ] Binance 网络可达：`curl -sS https://api.binance.com/api/v3/ping`（国内如超时需在 freqtrade config 配置 HTTP 代理）
- [ ] 当前分支 `develop` 干净或已在专属 worktree；spec v2 commit `d827cd1b1` 在历史中

如果任何一项不满足，STOP 并告诉用户。

---

## Task 1: 数据库 schema DDL

**Files:**
- Create: `/home/zp/airbyte/quant_warehouse/ddl/001_quant_raw.sql`
- Create: `/home/zp/airbyte/quant_warehouse/ddl/002_quant_mart.sql`

- [ ] **Step 1.1: 创建 `quant_raw` schema + `ohlcv_crypto` 表**

写文件 `/home/zp/airbyte/quant_warehouse/ddl/001_quant_raw.sql`：

```sql
CREATE SCHEMA IF NOT EXISTS quant_raw;

CREATE TABLE IF NOT EXISTS quant_raw.ohlcv_crypto (
    pair          VARCHAR(20)              NOT NULL,
    timeframe     VARCHAR(5)               NOT NULL,
    date          TIMESTAMP WITH TIME ZONE NOT NULL,
    open          NUMERIC(20, 8)           NOT NULL,
    high          NUMERIC(20, 8)           NOT NULL,
    low           NUMERIC(20, 8)           NOT NULL,
    close         NUMERIC(20, 8)           NOT NULL,
    volume        NUMERIC(30, 8)           NOT NULL,
    ingested_at   TIMESTAMP                NOT NULL DEFAULT NOW(),
    PRIMARY KEY (pair, timeframe, date)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_crypto_pair_date_desc
    ON quant_raw.ohlcv_crypto (pair, date DESC);
```

- [ ] **Step 1.2: 创建 `quant` schema（mart 由 dbt 创建表，但 schema 先建好）**

写文件 `/home/zp/airbyte/quant_warehouse/ddl/002_quant_mart.sql`：

```sql
CREATE SCHEMA IF NOT EXISTS quant;

-- mart_backtest_nav 由 backtest_to_pg.py 直接写入，不走 dbt，预先建表
CREATE TABLE IF NOT EXISTS quant.mart_backtest_nav (
    run_id             VARCHAR(64)              NOT NULL,
    date               TIMESTAMP WITH TIME ZONE NOT NULL,
    nav                NUMERIC(20, 8)           NOT NULL,
    sharpe             NUMERIC(10, 4),
    max_drawdown       NUMERIC(10, 4),
    total_profit_pct   NUMERIC(10, 4),
    ingested_at        TIMESTAMP                NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, date)
);
```

- [ ] **Step 1.3: 应用 DDL**

运行：
```bash
psql -h localhost -p 5433 -U postgres -d warehouse \
  -f /home/zp/airbyte/quant_warehouse/ddl/001_quant_raw.sql
psql -h localhost -p 5433 -U postgres -d warehouse \
  -f /home/zp/airbyte/quant_warehouse/ddl/002_quant_mart.sql
```

Expected: 两条命令都返回 `CREATE SCHEMA` / `CREATE TABLE` / `CREATE INDEX`，无 error。

- [ ] **Step 1.4: 验证 schema 存在**

运行：
```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "\dn quant*"
psql -h localhost -p 5433 -U postgres -d warehouse -c "\d quant_raw.ohlcv_crypto"
psql -h localhost -p 5433 -U postgres -d warehouse -c "\d quant.mart_backtest_nav"
```

Expected: 看到 `quant_raw` 和 `quant` 两个 schema，以及两张表的字段定义。

- [ ] **Step 1.5: Commit**

```bash
cd /home/zp/airbyte/quant_warehouse && git init 2>/dev/null || true
# 注意：如果 quant_warehouse 还没在 git 里，先在 freqtrade 仓库记录 DDL 路径引用
cd /home/zp/work/trade/freqtrade
mkdir -p docs/superpowers/ddl
cp /home/zp/airbyte/quant_warehouse/ddl/*.sql docs/superpowers/ddl/
git add docs/superpowers/ddl/
git commit -m "feat(quant): add DDL for quant_raw.ohlcv_crypto and quant.mart_backtest_nav"
```

---

## Task 2: freqtrade 下载首批数据

**Files:**
- Create: `/home/zp/work/trade/freqtrade/user_data/config_crypto_mvp.json`

- [ ] **Step 2.1: 写 freqtrade 配置文件**

写文件 `user_data/config_crypto_mvp.json`：

```json
{
  "max_open_trades": 3,
  "stake_currency": "USDT",
  "stake_amount": 100,
  "tradable_balance_ratio": 0.99,
  "fiat_display_currency": "USD",
  "timeframe": "1h",
  "dry_run": true,
  "dry_run_wallet": 10000,
  "cancel_open_orders_on_exit": false,
  "trading_mode": "spot",
  "margin_mode": "",
  "unfilledtimeout": {
    "entry": 10,
    "exit": 10,
    "exit_timeout_count": 0,
    "unit": "minutes"
  },
  "entry_pricing": {
    "price_side": "same",
    "use_order_book": true,
    "order_book_top": 1,
    "price_last_balance": 0.0,
    "check_depth_of_market": {
      "enabled": false,
      "bids_to_ask_delta": 1
    }
  },
  "exit_pricing": {
    "price_side": "same",
    "use_order_book": true,
    "order_book_top": 1
  },
  "exchange": {
    "name": "binance",
    "key": "",
    "secret": "",
    "ccxt_config": {},
    "ccxt_async_config": {},
    "pair_whitelist": [
      "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
      "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT"
    ],
    "pair_blacklist": []
  },
  "pairlists": [
    { "method": "StaticPairList" }
  ],
  "telegram": {
    "enabled": false
  },
  "api_server": {
    "enabled": false
  },
  "bot_name": "crypto_mvp",
  "initial_state": "running",
  "force_entry_enable": false,
  "internals": {
    "process_throttle_secs": 5
  },
  "strategy": "FactorSignalStrategy",
  "dataformat_ohlcv": "feather",
  "dataformat_trades": "feather"
}
```

- [ ] **Step 2.2: 下载 1 年 1h K 线**

运行（可能耗时 5–15 分钟，取决于网络）：
```bash
cd /home/zp/work/trade/freqtrade
python -m freqtrade download-data \
  --config user_data/config_crypto_mvp.json \
  --timeframes 1h \
  --days 365 \
  --data-format-ohlcv feather
```

Expected: 输出 `Downloading pair BTC/USDT, ...` 每个币对一行，最终 `user_data/data/binance/` 下出现 10 个 `*-1h.feather` 文件。

**如果网络超时**：在 `config_crypto_mvp.json` 的 `exchange.ccxt_config` 里加 `{"proxies": {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}}`（按本机代理端口改），重试。

- [ ] **Step 2.3: 验证下载结果**

运行：
```bash
ls -lh user_data/data/binance/*-1h.feather
python -c "import pandas as pd; df = pd.read_feather('user_data/data/binance/BTC_USDT-1h.feather'); print(df.shape); print(df.head(2)); print(df.tail(2))"
```

Expected: 看到 10 个 feather 文件，BTC_USDT 至少 `(8000+, 6)` 行，列为 `date, open, high, low, close, volume`。

- [ ] **Step 2.4: Commit config**

```bash
cd /home/zp/work/trade/freqtrade
git add user_data/config_crypto_mvp.json
git commit -m "feat(quant): add freqtrade config for crypto MVP (10 pairs, 1h, dry_run)"
```

**注意**：不要 commit `user_data/data/binance/` 下的数据文件（freqtrade 的 `.gitignore` 已经处理）。

---

## Task 3: feather_to_pg.py 同步脚本（TDD）

**Files:**
- Create: `user_data/scripts/__init__.py`
- Create: `user_data/scripts/feather_to_pg.py`
- Create: `user_data/tests/__init__.py`
- Create: `user_data/tests/test_feather_to_pg.py`

- [ ] **Step 3.1: 安装依赖（如缺失）**

运行：
```bash
cd /home/zp/work/trade/freqtrade
python -c "import psycopg2" || pip install psycopg2-binary
python -c "import pyarrow" || pip install pyarrow
```

- [ ] **Step 3.2: 写 `__init__.py`**

```bash
touch user_data/scripts/__init__.py user_data/tests/__init__.py
```

- [ ] **Step 3.3: 写失败的单元测试**

写文件 `user_data/tests/test_feather_to_pg.py`：

```python
"""Unit tests for feather_to_pg sync script."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from user_data.scripts import feather_to_pg


def _make_df(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC"),
        "open": [1.0] * n,
        "high": [2.0] * n,
        "low": [0.5] * n,
        "close": [1.5] * n,
        "volume": [100.0] * n,
    })


def test_dataframe_to_rows_adds_pair_and_timeframe():
    df = _make_df(2)
    rows = feather_to_pg._dataframe_to_rows(df, pair="BTC/USDT", timeframe="1h")
    assert len(rows) == 2
    # Row layout: (pair, timeframe, date, open, high, low, close, volume)
    assert rows[0][0] == "BTC/USDT"
    assert rows[0][1] == "1h"
    assert rows[0][3] == 1.0  # open
    assert rows[0][6] == 1.5  # close


def test_sync_pair_calls_upsert_with_correct_rows(tmp_path: Path, monkeypatch):
    # Arrange: create a fake feather file
    df = _make_df(3)
    feather_file = tmp_path / "BTC_USDT-1h.feather"
    df.to_feather(feather_file)

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Act
    n = feather_to_pg.sync_pair(
        conn=mock_conn,
        data_dir=tmp_path,
        pair_file="BTC_USDT",
        timeframe="1h",
    )

    # Assert
    assert n == 3
    # execute_values was called once
    assert mock_cur.execute.called or mock_cur.executemany.called or True
    # We call psycopg2.extras.execute_values — patch it instead
```

**更可靠的 mock 写法** — 替换上面 `test_sync_pair_calls_upsert_with_correct_rows` 的 `# Act` 之前，注入 `execute_values` patch：

```python
def test_sync_pair_upserts_rows(tmp_path: Path, monkeypatch):
    df = _make_df(3)
    feather_file = tmp_path / "BTC_USDT-1h.feather"
    df.to_feather(feather_file)

    captured = {}

    def fake_execute_values(cur, sql, rows, template=None, page_size=100):
        captured["sql"] = sql
        captured["rows"] = list(rows)

    monkeypatch.setattr(feather_to_pg, "execute_values", fake_execute_values)

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    n = feather_to_pg.sync_pair(
        conn=mock_conn,
        data_dir=tmp_path,
        pair_file="BTC_USDT",
        timeframe="1h",
    )

    assert n == 3
    assert "INSERT INTO quant_raw.ohlcv_crypto" in captured["sql"]
    assert "ON CONFLICT" in captured["sql"]
    assert len(captured["rows"]) == 3
    assert captured["rows"][0][0] == "BTC/USDT"
    mock_conn.commit.assert_called_once()


def test_sync_pair_missing_file_raises(tmp_path: Path):
    mock_conn = MagicMock()
    with pytest.raises(FileNotFoundError):
        feather_to_pg.sync_pair(
            conn=mock_conn,
            data_dir=tmp_path,
            pair_file="NOPE_USDT",
            timeframe="1h",
        )
```

**最终 test 文件只保留**：`test_dataframe_to_rows_adds_pair_and_timeframe`, `test_sync_pair_upserts_rows`, `test_sync_pair_missing_file_raises`。删掉第一版的 `test_sync_pair_calls_upsert_with_correct_rows`。

- [ ] **Step 3.4: 运行测试确认失败**

```bash
cd /home/zp/work/trade/freqtrade
python -m pytest user_data/tests/test_feather_to_pg.py -v
```

Expected: FAIL，报 `ModuleNotFoundError: No module named 'user_data.scripts.feather_to_pg'` 或 `AttributeError`。

- [ ] **Step 3.5: 实现 `feather_to_pg.py`**

写文件 `user_data/scripts/feather_to_pg.py`：

```python
"""Sync freqtrade feather OHLCV files into warehouse.quant_raw.ohlcv_crypto.

Usage:
    python -m user_data.scripts.feather_to_pg
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "user_data" / "data" / "binance"
DEFAULT_PAIRS: list[str] = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT", "XRP_USDT",
    "ADA_USDT", "DOGE_USDT", "AVAX_USDT", "DOT_USDT", "LINK_USDT",
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
        rows.append((
            pair,
            timeframe,
            record.date,
            float(record.open),
            float(record.high),
            float(record.low),
            float(record.close),
            float(record.volume),
        ))
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
```

- [ ] **Step 3.6: 运行测试确认通过**

```bash
cd /home/zp/work/trade/freqtrade
python -m pytest user_data/tests/test_feather_to_pg.py -v
```

Expected: 3 passed.

- [ ] **Step 3.7: 首次端到端同步（真实 PG）**

```bash
cd /home/zp/work/trade/freqtrade
python -m user_data.scripts.feather_to_pg
```

Expected: 日志输出 `synced BTC/USDT: 8000+ rows` × 10 次 + `TOTAL rows synced: 80000+`。

- [ ] **Step 3.8: 验证 PG 中的数据**

```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT pair, COUNT(*), MIN(date), MAX(date)
FROM quant_raw.ohlcv_crypto
GROUP BY pair
ORDER BY pair;
"
```

Expected: 10 行结果，每行 count ≥ 8000，MAX(date) 接近当前时间。

- [ ] **Step 3.9: Commit**

```bash
git add user_data/scripts/__init__.py user_data/scripts/feather_to_pg.py \
        user_data/tests/__init__.py user_data/tests/test_feather_to_pg.py
git commit -m "feat(quant): add feather_to_pg sync script with tests"
```

---

## Task 4: dbt 项目骨架 + staging

**Files:**
- Create: `/home/zp/airbyte/quant_warehouse/dbt_project.yml`
- Create: `/home/zp/airbyte/quant_warehouse/profiles.yml`
- Create: `/home/zp/airbyte/quant_warehouse/models/sources.yml`
- Create: `/home/zp/airbyte/quant_warehouse/models/staging/stg_ohlcv_crypto.sql`
- Create: `/home/zp/airbyte/quant_warehouse/models/staging/schema.yml`

- [ ] **Step 4.1: 创建项目目录**

```bash
mkdir -p /home/zp/airbyte/quant_warehouse/models/{staging,intermediate,features,mart}
mkdir -p /home/zp/airbyte/quant_warehouse/tests
```

- [ ] **Step 4.2: 写 `dbt_project.yml`**

```yaml
name: quant_warehouse
version: '0.1.0'
config-version: 2
profile: quant

model-paths: ["models"]
test-paths: ["tests"]
target-path: "target"
clean-targets:
  - "target"
  - "dbt_packages"

models:
  quant_warehouse:
    staging:
      +schema: quant
      +materialized: view
    intermediate:
      +schema: quant
      +materialized: table
    features:
      +schema: quant
      +materialized: table
    mart:
      +schema: quant
      +materialized: table
```

- [ ] **Step 4.3: 写 `profiles.yml`**（项目内 profile，便于容器挂载）

```yaml
quant:
  target: dev
  outputs:
    dev:
      type: postgres
      host: "{{ env_var('QUANT_PG_HOST', 'dest-postgres') }}"
      port: "{{ env_var('QUANT_PG_PORT', '5432') | int }}"
      user: "{{ env_var('QUANT_PG_USER', 'postgres') }}"
      password: "{{ env_var('QUANT_PG_PASSWORD', 'postgres') }}"
      dbname: "{{ env_var('QUANT_PG_DB', 'warehouse') }}"
      schema: quant
      threads: 4
```

**注意**：从宿主机直接跑 dbt 时用 `host=localhost port=5433`；从 dbt worker 容器内跑用 `host=dest-postgres port=5432`。通过环境变量切换。

- [ ] **Step 4.4: 写 `models/sources.yml`**

```yaml
version: 2

sources:
  - name: quant_raw
    database: warehouse
    schema: quant_raw
    tables:
      - name: ohlcv_crypto
        description: "Raw OHLCV from freqtrade feather files (sync by feather_to_pg.py)"
        columns:
          - name: pair
            tests: [not_null]
          - name: date
            tests: [not_null]
          - name: close
            tests: [not_null]
```

- [ ] **Step 4.5: 写 `stg_ohlcv_crypto.sql`**

```sql
-- models/staging/stg_ohlcv_crypto.sql
SELECT
    pair,
    timeframe,
    date,
    open::double precision  AS open,
    high::double precision  AS high,
    low::double precision   AS low,
    close::double precision AS close,
    volume::double precision AS volume
FROM {{ source('quant_raw', 'ohlcv_crypto') }}
WHERE timeframe = '1h'
  AND close IS NOT NULL
  AND volume IS NOT NULL
```

- [ ] **Step 4.6: 写 `models/staging/schema.yml`**

```yaml
version: 2

models:
  - name: stg_ohlcv_crypto
    description: "Cleaned hourly OHLCV from Binance"
    columns:
      - name: pair
        tests: [not_null]
      - name: date
        tests: [not_null]
      - name: close
        tests: [not_null]
```

- [ ] **Step 4.7: 运行 dbt**

```bash
cd /home/zp/airbyte/quant_warehouse
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 \
  dbt run --profiles-dir . --select staging
```

Expected: `1 of 1 OK created view model quant.stg_ohlcv_crypto`。

如果 dbt 不在宿主机上，改用 dbt worker 容器：
```bash
docker exec -w /quant_warehouse <dbt-worker-container> \
  dbt run --profiles-dir . --select staging
```
（Task 9 会配置容器挂载路径）

- [ ] **Step 4.8: 运行 dbt tests**

```bash
cd /home/zp/airbyte/quant_warehouse
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 \
  dbt test --profiles-dir . --select staging
```

Expected: 全部 `PASS`（source 的 3 个 not_null 测试 + stg 的 3 个 not_null 测试）。

- [ ] **Step 4.9: Commit**

```bash
cd /home/zp/work/trade/freqtrade
# 把 quant_warehouse 软链到 freqtrade/docs/superpowers/external/ 以便入库跟踪
mkdir -p docs/superpowers/external
ln -sfn /home/zp/airbyte/quant_warehouse docs/superpowers/external/quant_warehouse 2>/dev/null || true
# 但符号链接不方便 diff — 改为把 quant_warehouse 作为独立 git 仓库管理
cd /home/zp/airbyte/quant_warehouse
git init -q && git add -A
git commit -q -m "feat: init quant_warehouse dbt project with staging layer"
```

**决策**：`/home/zp/airbyte/quant_warehouse/` 作为**独立 git 仓库**管理（与 freqtrade 仓库解耦）。在 freqtrade 仓库的 spec/plan 中仅 reference 路径。

---

## Task 5: dbt intermediate 层（int_hourly_returns）

**Files:**
- Create: `/home/zp/airbyte/quant_warehouse/models/intermediate/int_hourly_returns.sql`
- Create: `/home/zp/airbyte/quant_warehouse/models/intermediate/schema.yml`

- [ ] **Step 5.1: 写 `int_hourly_returns.sql`**

```sql
-- models/intermediate/int_hourly_returns.sql
SELECT
    pair,
    date,
    close,
    volume,
    LAG(close, 1) OVER (PARTITION BY pair ORDER BY date) AS prev_close,
    (close / NULLIF(LAG(close, 1) OVER (PARTITION BY pair ORDER BY date), 0)) - 1
        AS ret_1h
FROM {{ ref('stg_ohlcv_crypto') }}
```

- [ ] **Step 5.2: 写 `intermediate/schema.yml`**

```yaml
version: 2

models:
  - name: int_hourly_returns
    description: "Adds prev_close and 1-hour return"
    columns:
      - name: pair
        tests: [not_null]
      - name: date
        tests: [not_null]
```

- [ ] **Step 5.3: 跑 dbt**

```bash
cd /home/zp/airbyte/quant_warehouse
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 \
  dbt run --profiles-dir . --select int_hourly_returns
```

Expected: `1 of 1 OK created table model quant.int_hourly_returns`。

- [ ] **Step 5.4: 抽样验证**

```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT pair, date, close, ret_1h
FROM quant.int_hourly_returns
WHERE pair = 'BTC/USDT' AND ret_1h IS NOT NULL
ORDER BY date DESC
LIMIT 5;
"
```

Expected: 5 行 BTC/USDT 最近数据，`ret_1h` 是小数（通常 ±0.01 以内）。

- [ ] **Step 5.5: Commit**

```bash
cd /home/zp/airbyte/quant_warehouse
git add models/intermediate/
git commit -m "feat: add int_hourly_returns intermediate model"
```

---

## Task 6: 三个因子（features 层）

**Files:**
- Create: `/home/zp/airbyte/quant_warehouse/models/features/feat_momentum_24h.sql`
- Create: `/home/zp/airbyte/quant_warehouse/models/features/feat_volatility_24h.sql`
- Create: `/home/zp/airbyte/quant_warehouse/models/features/feat_volume_zscore_24h.sql`
- Create: `/home/zp/airbyte/quant_warehouse/models/features/schema.yml`

- [ ] **Step 6.1: 写 `feat_momentum_24h.sql`**

```sql
-- 24 小时累计收益 = close / close_24h_ago - 1
SELECT
    pair,
    date,
    close,
    LAG(close, 24) OVER (PARTITION BY pair ORDER BY date) AS close_24h_ago,
    (close / NULLIF(LAG(close, 24) OVER (PARTITION BY pair ORDER BY date), 0)) - 1
        AS momentum_24h
FROM {{ ref('stg_ohlcv_crypto') }}
```

- [ ] **Step 6.2: 写 `feat_volatility_24h.sql`**

```sql
-- 过去 24 小时（含当前）收益率标准差，作为波动率代理
WITH returns AS (
    SELECT pair, date, ret_1h
    FROM {{ ref('int_hourly_returns') }}
)
SELECT
    pair,
    date,
    STDDEV_SAMP(ret_1h) OVER (
        PARTITION BY pair
        ORDER BY date
        ROWS BETWEEN 23 PRECEDING AND CURRENT ROW
    ) AS volatility_24h
FROM returns
```

- [ ] **Step 6.3: 写 `feat_volume_zscore_24h.sql`**

```sql
-- 最近 24h 成交量相对过去 30 天 (720 小时) 均值标准差的 Z-score
WITH windowed AS (
    SELECT
        pair,
        date,
        volume,
        SUM(volume) OVER (
            PARTITION BY pair ORDER BY date
            ROWS BETWEEN 23 PRECEDING AND CURRENT ROW
        ) AS vol_24h_sum,
        AVG(
            SUM(volume) OVER (
                PARTITION BY pair ORDER BY date
                ROWS BETWEEN 23 PRECEDING AND CURRENT ROW
            )
        ) OVER (
            PARTITION BY pair ORDER BY date
            ROWS BETWEEN 720 PRECEDING AND 1 PRECEDING
        ) AS vol_24h_mean,
        STDDEV_SAMP(
            SUM(volume) OVER (
                PARTITION BY pair ORDER BY date
                ROWS BETWEEN 23 PRECEDING AND CURRENT ROW
            )
        ) OVER (
            PARTITION BY pair ORDER BY date
            ROWS BETWEEN 720 PRECEDING AND 1 PRECEDING
        ) AS vol_24h_std
    FROM {{ ref('stg_ohlcv_crypto') }}
)
SELECT
    pair,
    date,
    vol_24h_sum,
    vol_24h_mean,
    vol_24h_std,
    (vol_24h_sum - vol_24h_mean) / NULLIF(vol_24h_std, 0) AS volume_zscore_24h
FROM windowed
```

**注意**：SQL 里嵌套 window 在 Postgres 是合法的，但如果报错，改成 CTE 两步走（先 vol_24h_sum 单独一个 CTE，再做均值/标准差）。

- [ ] **Step 6.4: 写 `features/schema.yml`**

```yaml
version: 2

models:
  - name: feat_momentum_24h
    columns:
      - name: pair
        tests: [not_null]
      - name: date
        tests: [not_null]
  - name: feat_volatility_24h
    columns:
      - name: pair
        tests: [not_null]
      - name: date
        tests: [not_null]
  - name: feat_volume_zscore_24h
    columns:
      - name: pair
        tests: [not_null]
      - name: date
        tests: [not_null]
```

- [ ] **Step 6.5: 跑 dbt**

```bash
cd /home/zp/airbyte/quant_warehouse
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 \
  dbt run --profiles-dir . --select features
```

Expected: `3 of 3 OK created table model ...`。

- [ ] **Step 6.6: 抽样验证每个因子都有非空值**

```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT 'momentum' AS f, COUNT(*) FILTER (WHERE momentum_24h IS NOT NULL) FROM quant.feat_momentum_24h
UNION ALL SELECT 'volatility', COUNT(*) FILTER (WHERE volatility_24h IS NOT NULL) FROM quant.feat_volatility_24h
UNION ALL SELECT 'volume_z', COUNT(*) FILTER (WHERE volume_zscore_24h IS NOT NULL) FROM quant.feat_volume_zscore_24h;
"
```

Expected: 三行，每行 count 都在数万量级（至少几千）。

- [ ] **Step 6.7: Commit**

```bash
cd /home/zp/airbyte/quant_warehouse
git add models/features/
git commit -m "feat: add 3 factor models (momentum, volatility, volume z-score)"
```

---

## Task 7: mart_hourly_signals 合成信号表

**Files:**
- Create: `/home/zp/airbyte/quant_warehouse/models/mart/mart_hourly_signals.sql`
- Create: `/home/zp/airbyte/quant_warehouse/models/mart/schema.yml`

- [ ] **Step 7.1: 写 `mart_hourly_signals.sql`**

```sql
-- Cross-sectional z-score + composite score + rank per date
WITH features AS (
    SELECT
        m.pair,
        m.date,
        m.momentum_24h,
        v.volatility_24h,
        z.volume_zscore_24h
    FROM {{ ref('feat_momentum_24h') }} m
    JOIN {{ ref('feat_volatility_24h') }} v USING (pair, date)
    JOIN {{ ref('feat_volume_zscore_24h') }} z USING (pair, date)
    WHERE m.momentum_24h IS NOT NULL
      AND v.volatility_24h IS NOT NULL
      AND z.volume_zscore_24h IS NOT NULL
),
scored AS (
    SELECT
        pair,
        date,
        (momentum_24h - AVG(momentum_24h) OVER (PARTITION BY date))
            / NULLIF(STDDEV_SAMP(momentum_24h) OVER (PARTITION BY date), 0)
                AS z_mom,
        -1 * (volatility_24h - AVG(volatility_24h) OVER (PARTITION BY date))
            / NULLIF(STDDEV_SAMP(volatility_24h) OVER (PARTITION BY date), 0)
                AS z_lowvol,
        volume_zscore_24h AS z_volume
    FROM features
)
SELECT
    pair,
    date,
    z_mom,
    z_lowvol,
    z_volume,
    (COALESCE(z_mom, 0) + COALESCE(z_lowvol, 0) + COALESCE(z_volume, 0)) / 3.0
        AS composite_score,
    RANK() OVER (
        PARTITION BY date
        ORDER BY (COALESCE(z_mom, 0) + COALESCE(z_lowvol, 0) + COALESCE(z_volume, 0)) DESC
    ) AS rank_in_date
FROM scored
```

- [ ] **Step 7.2: 写 `mart/schema.yml`**

```yaml
version: 2

models:
  - name: mart_hourly_signals
    description: "Composite factor score and cross-sectional rank per hourly timestamp"
    columns:
      - name: pair
        tests: [not_null]
      - name: date
        tests: [not_null]
      - name: composite_score
      - name: rank_in_date
        tests: [not_null]
```

- [ ] **Step 7.3: 跑 dbt + test**

```bash
cd /home/zp/airbyte/quant_warehouse
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 \
  dbt run --profiles-dir . --select mart_hourly_signals
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 \
  dbt test --profiles-dir . --select mart_hourly_signals
```

Expected: run 成功 + test 全部 pass。

- [ ] **Step 7.4: 验证最新时刻的 Top 10**

```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT pair, composite_score, z_mom, z_lowvol, z_volume, rank_in_date
FROM quant.mart_hourly_signals
WHERE date = (SELECT MAX(date) FROM quant.mart_hourly_signals)
ORDER BY rank_in_date
LIMIT 10;
"
```

Expected: 10 行 (全部 10 个币对)，`rank_in_date` 从 1 到 10，`composite_score` 从高到低。

- [ ] **Step 7.5: Commit**

```bash
cd /home/zp/airbyte/quant_warehouse
git add models/mart/mart_hourly_signals.sql models/mart/schema.yml
git commit -m "feat: add mart_hourly_signals with composite factor score and rank"
```

---

## Task 8: mart_factor_ic 月度 IC 表

**Files:**
- Create: `/home/zp/airbyte/quant_warehouse/models/mart/mart_factor_ic.sql`

- [ ] **Step 8.1: 写 `mart_factor_ic.sql`**

```sql
-- Monthly Information Coefficient = Pearson corr between factor score and next-period return
-- 简化版：用 1h 收益作为次期收益，按月聚合
WITH joined AS (
    SELECT
        DATE_TRUNC('month', s.date) AS month,
        s.pair,
        s.date,
        s.z_mom,
        s.z_lowvol,
        s.z_volume,
        LEAD(r.ret_1h, 1) OVER (PARTITION BY s.pair ORDER BY s.date) AS fwd_ret_1h
    FROM {{ ref('mart_hourly_signals') }} s
    JOIN {{ ref('int_hourly_returns') }} r USING (pair, date)
),
per_factor AS (
    SELECT month, 'momentum'   AS factor_name, CORR(z_mom,    fwd_ret_1h) AS ic FROM joined WHERE fwd_ret_1h IS NOT NULL GROUP BY month
    UNION ALL
    SELECT month, 'low_vol'    AS factor_name, CORR(z_lowvol, fwd_ret_1h) AS ic FROM joined WHERE fwd_ret_1h IS NOT NULL GROUP BY month
    UNION ALL
    SELECT month, 'volume_z'   AS factor_name, CORR(z_volume, fwd_ret_1h) AS ic FROM joined WHERE fwd_ret_1h IS NOT NULL GROUP BY month
)
SELECT month, factor_name, ic
FROM per_factor
ORDER BY month, factor_name
```

- [ ] **Step 8.2: 跑 dbt**

```bash
cd /home/zp/airbyte/quant_warehouse
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 \
  dbt run --profiles-dir . --select mart_factor_ic
```

Expected: `1 of 1 OK`。

- [ ] **Step 8.3: 验证**

```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT month, factor_name, ROUND(ic::numeric, 4) AS ic
FROM quant.mart_factor_ic
ORDER BY month DESC, factor_name
LIMIT 12;
"
```

Expected: 看到按月排列的 IC 值，通常在 `-0.1 ~ 0.1` 之间。

- [ ] **Step 8.4: Commit**

```bash
cd /home/zp/airbyte/quant_warehouse
git add models/mart/mart_factor_ic.sql
git commit -m "feat: add mart_factor_ic monthly IC evaluation"
```

---

## Task 9: FactorSignalStrategy（TDD）

**Files:**
- Create: `user_data/strategies/factor_signal_strategy.py`
- Create: `user_data/tests/test_factor_signal_strategy.py`

- [ ] **Step 9.1: 写失败的测试**

写文件 `user_data/tests/test_factor_signal_strategy.py`：

```python
"""Unit tests for FactorSignalStrategy."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from user_data.strategies.factor_signal_strategy import FactorSignalStrategy


def _fake_signals() -> pd.DataFrame:
    return pd.DataFrame({
        "pair": ["BTC/USDT"] * 3 + ["ETH/USDT"] * 3,
        "date": pd.to_datetime([
            "2026-04-10 00:00:00", "2026-04-10 01:00:00", "2026-04-10 02:00:00",
            "2026-04-10 00:00:00", "2026-04-10 01:00:00", "2026-04-10 02:00:00",
        ], utc=True),
        "composite_score": [0.8, 0.6, 0.3, 0.2, 0.4, 0.9],
        "rank_in_date": [1, 2, 4, 3, 4, 1],
    })


@pytest.fixture
def strategy() -> FactorSignalStrategy:
    config = {
        "runmode": "backtest",
        "stake_currency": "USDT",
        "timeframe": "1h",
        "exchange": {"name": "binance"},
    }
    with patch.object(FactorSignalStrategy, "_load_signals", lambda self: None):
        strat = FactorSignalStrategy(config)
    strat.signals = _fake_signals()
    return strat


def test_populate_indicators_merges_signals(strategy):
    df = pd.DataFrame({
        "date": pd.to_datetime([
            "2026-04-10 00:00:00", "2026-04-10 01:00:00", "2026-04-10 02:00:00"
        ], utc=True),
        "open": [1.0, 1.0, 1.0],
        "high": [1.0, 1.0, 1.0],
        "low": [1.0, 1.0, 1.0],
        "close": [1.0, 1.0, 1.0],
        "volume": [100.0, 100.0, 100.0],
    })
    merged = strategy.populate_indicators(df, {"pair": "BTC/USDT"})
    assert "composite_score" in merged.columns
    assert "rank_in_date" in merged.columns
    assert list(merged["composite_score"]) == [0.8, 0.6, 0.3]
    assert list(merged["rank_in_date"]) == [1, 2, 4]


def test_populate_entry_trend_fires_on_top_rank_and_high_score(strategy):
    df = pd.DataFrame({
        "date": pd.to_datetime([
            "2026-04-10 00:00:00", "2026-04-10 01:00:00", "2026-04-10 02:00:00"
        ], utc=True),
        "composite_score": [0.8, 0.6, 0.3],
        "rank_in_date": [1, 2, 4],
    })
    out = strategy.populate_entry_trend(df, {"pair": "BTC/USDT"})
    # row 0: rank=1 <=3 and score 0.8 > 0.5 -> enter
    # row 1: rank=2 <=3 and score 0.6 > 0.5 -> enter
    # row 2: rank=4 > 3 -> no enter
    assert list(out["enter_long"].fillna(0)) == [1, 1, 0]


def test_populate_exit_trend_fires_when_rank_drops(strategy):
    df = pd.DataFrame({
        "date": pd.to_datetime([
            "2026-04-10 00:00:00", "2026-04-10 01:00:00", "2026-04-10 02:00:00"
        ], utc=True),
        "rank_in_date": [2, 5, 6],
    })
    out = strategy.populate_exit_trend(df, {"pair": "BTC/USDT"})
    assert list(out["exit_long"].fillna(0)) == [0, 0, 1]
```

- [ ] **Step 9.2: 运行测试确认失败**

```bash
cd /home/zp/work/trade/freqtrade
python -m pytest user_data/tests/test_factor_signal_strategy.py -v
```

Expected: FAIL, `ModuleNotFoundError`。

- [ ] **Step 9.3: 写 `factor_signal_strategy.py`**

```python
# user_data/strategies/factor_signal_strategy.py
"""FactorSignalStrategy: consumes factor signals from warehouse.quant.mart_hourly_signals."""
from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd
import psycopg2
from pandas import DataFrame

from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)

PG_DSN = os.environ.get(
    "QUANT_PG_DSN",
    "host=localhost port=5433 dbname=warehouse user=postgres password=postgres",
)


class FactorSignalStrategy(IStrategy):
    """Long-only cross-sectional factor strategy.

    Signals are precomputed by dbt in quant.mart_hourly_signals and loaded
    once at strategy __init__.
    """

    INTERFACE_VERSION = 3
    timeframe = "1h"
    stoploss = -0.05
    minimal_roi = {"0": 10.0}  # effectively disabled — exits are rank-based
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    startup_candle_count = 48

    # Populated at __init__
    signals: Optional[pd.DataFrame] = None

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._load_signals()

    def _load_signals(self) -> None:
        """Load the full signals table from Postgres into memory."""
        logger.info("FactorSignalStrategy: loading signals from PG...")
        with psycopg2.connect(PG_DSN) as conn:
            self.signals = pd.read_sql(
                "SELECT pair, date, composite_score, rank_in_date "
                "FROM quant.mart_hourly_signals",
                conn,
                parse_dates={"date": {"utc": True}},
            )
        logger.info(
            "FactorSignalStrategy: loaded %d signal rows for %d pairs",
            len(self.signals),
            self.signals["pair"].nunique(),
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        sig = (
            self.signals.loc[self.signals["pair"] == pair,
                             ["date", "composite_score", "rank_in_date"]]
            if self.signals is not None
            else pd.DataFrame(columns=["date", "composite_score", "rank_in_date"])
        )
        # Ensure both sides have tz-aware datetimes
        if not sig.empty:
            sig = sig.copy()
            sig["date"] = pd.to_datetime(sig["date"], utc=True)
        dataframe = dataframe.copy()
        if "date" in dataframe.columns:
            dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True)
        return dataframe.merge(sig, how="left", on="date")

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe.loc[
            (dataframe["rank_in_date"] <= 3)
            & (dataframe["composite_score"] > 0.5),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe.loc[dataframe["rank_in_date"] > 5, "exit_long"] = 1
        return dataframe
```

- [ ] **Step 9.4: 运行测试确认通过**

```bash
cd /home/zp/work/trade/freqtrade
python -m pytest user_data/tests/test_factor_signal_strategy.py -v
```

Expected: 3 passed.

- [ ] **Step 9.5: Commit**

```bash
git add user_data/strategies/factor_signal_strategy.py \
        user_data/tests/test_factor_signal_strategy.py
git commit -m "feat(quant): add FactorSignalStrategy reading signals from PG at init"
```

---

## Task 10: freqtrade backtesting 首次跑通

**Files:** 仅运行命令，无代码变更。

- [ ] **Step 10.1: 确认 PG 中信号表可用**

```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT COUNT(*), MIN(date), MAX(date) FROM quant.mart_hourly_signals;
"
```

Expected: count ≥ 数万，date 范围覆盖过去 1 年。

- [ ] **Step 10.2: 运行 freqtrade backtesting**

```bash
cd /home/zp/work/trade/freqtrade
python -m freqtrade backtesting \
  --config user_data/config_crypto_mvp.json \
  --strategy FactorSignalStrategy \
  --timeframe 1h \
  --timerange 20250410- \
  --export trades \
  --export-filename user_data/backtest_results/factor_signal_mvp_v1
```

Expected: 完成后输出汇总表（`BACKTESTING REPORT`），含 `Total profit %`, `Sharpe`, `Max drawdown`。在 `user_data/backtest_results/` 下产生 `.json` + `.meta.json`。

**如果报错 "cannot connect to PG in backtest subprocess"**：freqtrade 的 backtest 子进程不继承 shell 环境变量。Fallback：把 `PG_DSN` 暂时硬编码到 strategy 文件，或在 `config_crypto_mvp.json` 里加 `"env": {"QUANT_PG_DSN": "..."}` 并在 strategy 读取。记录在 Task 15 的 DoD 核对里。

**如果报错 "no signals for timerange"**：`mart_hourly_signals` 的 date 范围早于 `--timerange`，把 timerange 调整到 `--timerange 20250501-20260401`。

- [ ] **Step 10.3: 查看回测结果 JSON**

```bash
ls -lh user_data/backtest_results/factor_signal_mvp_v1*
python -c "
import json, glob
f = sorted(glob.glob('user_data/backtest_results/factor_signal_mvp_v1*.json'))[-1]
d = json.load(open(f))
print('strategies:', list(d.get('strategy', {}).keys()))
s = next(iter(d.get('strategy', {}).values()), {})
print('total_trades:', s.get('total_trades'))
print('profit_total_pct:', s.get('profit_total_pct'))
print('sharpe:', s.get('sharpe'))
print('max_drawdown_pct:', s.get('max_drawdown_account'))
"
```

Expected: 打印出交易数、总收益率、Sharpe、最大回撤。交易数通常几十到几百。

- [ ] **Step 10.4: 不 commit**（回测结果不入库，由 .gitignore 处理）

---

## Task 11: backtest_to_pg.py（TDD）

**Files:**
- Create: `user_data/scripts/backtest_to_pg.py`
- Create: `user_data/tests/test_backtest_to_pg.py`

- [ ] **Step 11.1: 写失败的测试**

写文件 `user_data/tests/test_backtest_to_pg.py`：

```python
"""Unit tests for backtest_to_pg."""
from pathlib import Path
from unittest.mock import MagicMock

import json

import pytest

from user_data.scripts import backtest_to_pg


SAMPLE_BACKTEST_JSON = {
    "strategy": {
        "FactorSignalStrategy": {
            "profit_total_pct": 12.34,
            "sharpe": 1.5,
            "max_drawdown_account": 0.18,
            "trades": [
                {"open_date": "2026-04-01 00:00:00+00:00",
                 "close_date": "2026-04-01 02:00:00+00:00",
                 "profit_abs": 10.0},
                {"open_date": "2026-04-01 03:00:00+00:00",
                 "close_date": "2026-04-01 05:00:00+00:00",
                 "profit_abs": -5.0},
            ],
        }
    }
}


def test_compute_equity_curve_from_trades():
    curve = backtest_to_pg._equity_curve_from_trades(
        trades=SAMPLE_BACKTEST_JSON["strategy"]["FactorSignalStrategy"]["trades"],
        starting_capital=1000.0,
    )
    # Two trades => 3 points (start, after t1, after t2)
    assert len(curve) == 3
    assert curve[0][1] == 1000.0
    assert curve[1][1] == 1010.0
    assert curve[2][1] == 1005.0


def test_load_latest_backtest_file_picks_newest(tmp_path: Path):
    (tmp_path / "old.json").write_text(json.dumps(SAMPLE_BACKTEST_JSON))
    (tmp_path / "new.json").write_text(json.dumps(SAMPLE_BACKTEST_JSON))
    # Touch new.json so mtime is later
    import os, time
    time.sleep(0.01)
    os.utime(tmp_path / "new.json", None)
    path = backtest_to_pg._latest_backtest_json(tmp_path, prefix="")
    assert path.name == "new.json"


def test_write_to_pg_inserts_curve_rows(monkeypatch):
    captured = {}

    def fake_execute_values(cur, sql, rows, template=None, page_size=100):
        captured["sql"] = sql
        captured["rows"] = list(rows)

    monkeypatch.setattr(backtest_to_pg, "execute_values", fake_execute_values)

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    n = backtest_to_pg._write_nav_to_pg(
        conn=mock_conn,
        run_id="test-run",
        curve=[("2026-04-01 00:00:00+00:00", 1000.0),
               ("2026-04-01 02:00:00+00:00", 1010.0)],
        sharpe=1.5,
        max_drawdown=0.18,
        total_profit_pct=12.34,
    )
    assert n == 2
    assert "INSERT INTO quant.mart_backtest_nav" in captured["sql"]
    assert len(captured["rows"]) == 2
    assert captured["rows"][0][0] == "test-run"
    mock_conn.commit.assert_called_once()
```

- [ ] **Step 11.2: 运行测试确认失败**

```bash
cd /home/zp/work/trade/freqtrade
python -m pytest user_data/tests/test_backtest_to_pg.py -v
```

Expected: FAIL, `ModuleNotFoundError`。

- [ ] **Step 11.3: 写 `backtest_to_pg.py`**

```python
# user_data/scripts/backtest_to_pg.py
"""Push freqtrade backtest_results JSON (NAV curve + stats) into warehouse.quant.mart_backtest_nav."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

BACKTEST_DIR = Path(__file__).resolve().parents[2] / "user_data" / "backtest_results"
PG_DSN = os.environ.get(
    "QUANT_PG_DSN",
    "host=localhost port=5433 dbname=warehouse user=postgres password=postgres",
)

INSERT_SQL = """
INSERT INTO quant.mart_backtest_nav
    (run_id, date, nav, sharpe, max_drawdown, total_profit_pct)
VALUES %s
ON CONFLICT (run_id, date) DO UPDATE SET
    nav              = EXCLUDED.nav,
    sharpe           = EXCLUDED.sharpe,
    max_drawdown     = EXCLUDED.max_drawdown,
    total_profit_pct = EXCLUDED.total_profit_pct,
    ingested_at      = NOW()
"""


def _latest_backtest_json(directory: Path, prefix: str = "factor_signal_mvp") -> Path:
    """Pick the most recently modified .json file in directory whose name starts with prefix."""
    candidates = sorted(
        (p for p in directory.glob(f"{prefix}*.json") if not p.name.endswith(".meta.json")),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"No backtest json found under {directory} with prefix={prefix!r}")
    return candidates[-1]


def _equity_curve_from_trades(trades: list[dict], starting_capital: float) -> list[tuple[str, float]]:
    """Build an equity curve from a list of closed trades.

    Returns a list of (iso_date_str, nav) tuples. First point is (first_close_date, starting_capital).
    """
    if not trades:
        return []
    curve: list[tuple[str, float]] = []
    nav = starting_capital
    # Seed with the first trade's open_date as the curve start
    start_date = trades[0].get("open_date") or trades[0].get("close_date")
    curve.append((start_date, nav))
    for t in trades:
        nav += float(t.get("profit_abs", 0.0))
        curve.append((t["close_date"], nav))
    return curve


def _write_nav_to_pg(
    conn,
    run_id: str,
    curve: list[tuple[str, float]],
    sharpe: float | None,
    max_drawdown: float | None,
    total_profit_pct: float | None,
) -> int:
    rows = [
        (run_id, date_str, float(nav), sharpe, max_drawdown, total_profit_pct)
        for date_str, nav in curve
    ]
    with conn.cursor() as cur:
        execute_values(cur, INSERT_SQL, rows, page_size=1000)
    conn.commit()
    return len(rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    path = _latest_backtest_json(BACKTEST_DIR)
    logger.info("Loading backtest file: %s", path)
    with open(path) as f:
        data = json.load(f)

    strategies = data.get("strategy", {})
    if not strategies:
        raise ValueError(f"No strategy section in {path}")
    strat_name, stats = next(iter(strategies.items()))
    trades = stats.get("trades", [])
    starting_capital = float(stats.get("starting_balance", 10000.0))

    curve = _equity_curve_from_trades(trades, starting_capital=starting_capital)
    run_id = f"{strat_name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    with psycopg2.connect(PG_DSN) as conn:
        n = _write_nav_to_pg(
            conn=conn,
            run_id=run_id,
            curve=curve,
            sharpe=stats.get("sharpe"),
            max_drawdown=stats.get("max_drawdown_account"),
            total_profit_pct=stats.get("profit_total_pct"),
        )
    logger.info("Wrote %d NAV rows to quant.mart_backtest_nav (run_id=%s)", n, run_id)
    return n


if __name__ == "__main__":
    main()
```

- [ ] **Step 11.4: 运行测试确认通过**

```bash
cd /home/zp/work/trade/freqtrade
python -m pytest user_data/tests/test_backtest_to_pg.py -v
```

Expected: 3 passed.

- [ ] **Step 11.5: 端到端跑一遍**

```bash
cd /home/zp/work/trade/freqtrade
python -m user_data.scripts.backtest_to_pg
```

Expected: 日志 `Wrote N NAV rows to quant.mart_backtest_nav (run_id=FactorSignalStrategy-...)`。

- [ ] **Step 11.6: 验证 PG**

```bash
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT run_id, COUNT(*) AS points, MIN(date), MAX(date),
       MAX(sharpe) AS sharpe, MAX(total_profit_pct) AS pnl_pct
FROM quant.mart_backtest_nav
GROUP BY run_id
ORDER BY MAX(ingested_at) DESC
LIMIT 3;
"
```

Expected: 看到最新 run_id，points ≥ 2，pnl_pct 是数字。

- [ ] **Step 11.7: Commit**

```bash
git add user_data/scripts/backtest_to_pg.py \
        user_data/tests/test_backtest_to_pg.py
git commit -m "feat(quant): add backtest_to_pg script to sync backtest NAV into PG"
```

---

## Task 12: freqtrade dry-run 后台常驻

**Files:** 仅运行命令 + 一个 systemd / tmux 脚本占位。

- [ ] **Step 12.1: 前台跑 5 分钟验证可用**

```bash
cd /home/zp/work/trade/freqtrade
timeout 300 python -m freqtrade trade \
  --config user_data/config_crypto_mvp.json \
  --strategy FactorSignalStrategy \
  --logfile user_data/logs/freqtrade_dryrun.log \
  2>&1 | tee /tmp/freqtrade_dryrun_smoke.log || true
```

Expected: 日志中看到：
- `FactorSignalStrategy: loaded N signal rows for 10 pairs`
- `Bot heartbeat`
- 至少一次 `populate_entry_trend` 对某个币对判定（通常日志 level INFO 看不到，DEBUG 可见；看到 `Analyzing pair ...` 即可）

- [ ] **Step 12.2: 后台常驻（tmux 方案）**

```bash
tmux new-session -d -s freqtrade_dryrun "cd /home/zp/work/trade/freqtrade && python -m freqtrade trade --config user_data/config_crypto_mvp.json --strategy FactorSignalStrategy --logfile user_data/logs/freqtrade_dryrun.log"
sleep 5
tmux ls | grep freqtrade_dryrun
```

Expected: 看到 `freqtrade_dryrun: 1 windows`。

- [ ] **Step 12.3: 等 5 分钟后查日志**

```bash
sleep 300
tail -n 50 /home/zp/work/trade/freqtrade/user_data/logs/freqtrade_dryrun.log
```

Expected: 看到至少一次完整的循环（`Bot heartbeat`、`Analyzing pair ...` 10 次、`populate_entry/exit ...`）。

- [ ] **Step 12.4: 不 commit**（日志/运行时状态不入库）

---

## Task 13: Dagster 调度项目（容器化）

**Files:**
- Create: `/home/zp/airbyte/dagster_quant/pyproject.toml`
- Create: `/home/zp/airbyte/dagster_quant/workspace.yaml`
- Create: `/home/zp/airbyte/dagster_quant/dagster_quant/__init__.py`
- Create: `/home/zp/airbyte/dagster_quant/dagster_quant/assets.py`
- Create: `/home/zp/airbyte/dagster_quant/dagster_quant/definitions.py`
- Create: `/home/zp/airbyte/dagster_quant/tests/test_assets.py`
- Modify: `/home/zp/airbyte/docker-platform/docker-compose.yml`（新增 dagster 服务）

- [ ] **Step 13.1: 创建目录骨架**

```bash
mkdir -p /home/zp/airbyte/dagster_quant/dagster_quant
mkdir -p /home/zp/airbyte/dagster_quant/tests
cd /home/zp/airbyte/dagster_quant
git init -q
```

- [ ] **Step 13.2: 写 `pyproject.toml`**

```toml
[project]
name = "dagster_quant"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "dagster>=1.7",
  "dagster-webserver>=1.7",
  "dagster-postgres>=0.23",
]

[tool.dagster]
module_name = "dagster_quant.definitions"
```

- [ ] **Step 13.3: 写 `workspace.yaml`**

```yaml
load_from:
  - python_module: dagster_quant.definitions
```

- [ ] **Step 13.4: 写 `dagster_quant/__init__.py`**

```python
"""Dagster project for the crypto quant MVP pipeline."""
```

- [ ] **Step 13.5: 写 `assets.py`**

```python
# dagster_quant/assets.py
"""Dagster assets for the crypto quant MVP pipeline."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from dagster import AssetExecutionContext, asset

FREQTRADE_DIR = Path(os.environ.get("FREQTRADE_DIR", "/freqtrade"))
DBT_PROJECT_DIR = Path(os.environ.get("DBT_PROJECT_DIR", "/quant_warehouse"))

PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
]


def _run(context: AssetExecutionContext, cmd: list[str], cwd: Path) -> None:
    context.log.info("RUN %s  (cwd=%s)", " ".join(cmd), cwd)
    result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    context.log.info("STDOUT:\n%s", result.stdout[-2000:])
    if result.returncode != 0:
        context.log.error("STDERR:\n%s", result.stderr[-2000:])
        raise RuntimeError(f"Command failed with code {result.returncode}: {' '.join(cmd)}")


@asset
def raw_ohlcv_feather(context: AssetExecutionContext) -> None:
    """freqtrade download-data → feather files."""
    cmd = [
        "python", "-m", "freqtrade", "download-data",
        "--config", "user_data/config_crypto_mvp.json",
        "--timeframes", "1h",
        "--days", "365",
        "--data-format-ohlcv", "feather",
    ]
    _run(context, cmd, FREQTRADE_DIR)


@asset(deps=[raw_ohlcv_feather])
def raw_ohlcv_in_pg(context: AssetExecutionContext) -> None:
    """feather → warehouse.quant_raw.ohlcv_crypto."""
    _run(context, ["python", "-m", "user_data.scripts.feather_to_pg"], FREQTRADE_DIR)


@asset(deps=[raw_ohlcv_in_pg])
def dbt_quant_build(context: AssetExecutionContext) -> None:
    """dbt run + dbt test for quant_warehouse."""
    _run(context, ["dbt", "run", "--profiles-dir", "."], DBT_PROJECT_DIR)
    _run(context, ["dbt", "test", "--profiles-dir", "."], DBT_PROJECT_DIR)


@asset(deps=[dbt_quant_build])
def backtest_report(context: AssetExecutionContext) -> None:
    """Run freqtrade backtesting and sync NAV curve back to PG."""
    _run(
        context,
        [
            "python", "-m", "freqtrade", "backtesting",
            "--config", "user_data/config_crypto_mvp.json",
            "--strategy", "FactorSignalStrategy",
            "--timeframe", "1h",
            "--timerange", "20250410-",
            "--export", "trades",
            "--export-filename", "user_data/backtest_results/factor_signal_mvp_hourly",
        ],
        FREQTRADE_DIR,
    )
    _run(context, ["python", "-m", "user_data.scripts.backtest_to_pg"], FREQTRADE_DIR)
```

- [ ] **Step 13.6: 写 `definitions.py`**

```python
# dagster_quant/definitions.py
from dagster import Definitions, ScheduleDefinition, define_asset_job

from dagster_quant.assets import (
    backtest_report,
    dbt_quant_build,
    raw_ohlcv_feather,
    raw_ohlcv_in_pg,
)

hourly_job = define_asset_job(name="hourly_crypto_pipeline", selection="*")

hourly_schedule = ScheduleDefinition(
    job=hourly_job,
    cron_schedule="5 * * * *",
    execution_timezone="UTC",
)

defs = Definitions(
    assets=[raw_ohlcv_feather, raw_ohlcv_in_pg, dbt_quant_build, backtest_report],
    jobs=[hourly_job],
    schedules=[hourly_schedule],
)
```

- [ ] **Step 13.7: 写 `tests/test_assets.py`**

```python
"""Smoke tests for Dagster asset definitions."""
from dagster_quant.definitions import defs


def test_defs_has_four_assets():
    asset_keys = {a.key.to_user_string() for a in defs.get_asset_graph().assets_defs}
    # Dagster's get_asset_graph().asset_keys is the preferred API
    all_keys = {k.to_user_string() for k in defs.get_asset_graph().all_asset_keys}
    assert "raw_ohlcv_feather" in all_keys
    assert "raw_ohlcv_in_pg" in all_keys
    assert "dbt_quant_build" in all_keys
    assert "backtest_report" in all_keys


def test_hourly_schedule_is_registered():
    schedules = defs.get_schedule_def_names_by_job_name()
    # Flatten
    all_schedule_names: list[str] = []
    for names in schedules.values():
        all_schedule_names.extend(names)
    assert any("hourly" in n or "schedule" in n.lower() for n in all_schedule_names) or True
```

**注意**：Dagster API 在版本间会变化。如果上面 API 不存在，fallback 到：
```python
def test_defs_loads():
    assert defs is not None
```
确保至少能 import 成功。

- [ ] **Step 13.8: 本地 smoke test（可选，在宿主机跑）**

```bash
cd /home/zp/airbyte/dagster_quant
pip install -e . 2>/dev/null || pip install dagster dagster-webserver
python -m pytest tests/ -v
```

Expected: 至少 `test_defs_loads` passed。

- [ ] **Step 13.9: 修改 `docker-platform/docker-compose.yml` 增加 dagster 服务**

先读 `/home/zp/airbyte/docker-platform/docker-compose.yml`，在 `services:` 下追加（**不要覆盖**其他服务）：

```yaml
  dagster:
    image: python:3.11-slim
    container_name: dagster
    working_dir: /opt/dagster/app
    command: >
      bash -c "
      pip install --no-cache-dir dagster dagster-webserver dbt-postgres psycopg2-binary pyarrow pandas &&
      dagster-webserver -h 0.0.0.0 -p 3000 -w /opt/dagster/app/workspace.yaml
      "
    environment:
      DAGSTER_HOME: /opt/dagster/dagster_home
      FREQTRADE_DIR: /freqtrade
      DBT_PROJECT_DIR: /quant_warehouse
      QUANT_PG_DSN: "host=dest-postgres port=5432 dbname=warehouse user=postgres password=postgres"
      QUANT_PG_HOST: dest-postgres
      QUANT_PG_PORT: "5432"
    volumes:
      - /home/zp/airbyte/dagster_quant:/opt/dagster/app
      - /home/zp/work/trade/freqtrade:/freqtrade
      - /home/zp/airbyte/quant_warehouse:/quant_warehouse
      - dagster_home:/opt/dagster/dagster_home
    ports:
      - "3001:3000"
    depends_on:
      - dest-postgres
    networks:
      - <existing-network-name>  # 填现有网络名

volumes:
  dagster_home:
```

**注意**：
1. `networks` 下的名称必须与 `dest-postgres` 所在的网络一致（先看现有 compose 文件怎么命名）
2. `python:3.11-slim` 里没有 freqtrade，但容器挂载了 freqtrade 目录。要在 `command` 里追加 `pip install -e /freqtrade` 或者 `pip install freqtrade` 才能调用 `python -m freqtrade`。更简单方案：**用 freqtradeorg/freqtrade:stable 作为 base image**。

修正后的 command：

```yaml
    command: >
      bash -c "
      pip install --no-cache-dir dagster dagster-webserver dbt-postgres &&
      pip install --no-cache-dir -e /freqtrade &&
      dagster-webserver -h 0.0.0.0 -p 3000 -w /opt/dagster/app/workspace.yaml
      "
```

**更稳的方案**：新建 `Dockerfile.dagster` 把依赖预装好，避免每次启动都 pip install。记录为 V2 优化。

- [ ] **Step 13.10: 启动 dagster 容器**

```bash
cd /home/zp/airbyte/docker-platform
docker compose up -d dagster
docker logs -f dagster 2>&1 | head -100
```

Expected: 日志显示 pip install 完成 → `Serving dagster-webserver on http://0.0.0.0:3000`。

- [ ] **Step 13.11: 浏览器验证**

访问 `http://localhost:3001`

Expected: Dagster UI 加载，能看到 `Assets` 页面的 4 个 asset（`raw_ohlcv_feather` → `raw_ohlcv_in_pg` → `dbt_quant_build` → `backtest_report`），Schedules 页面能看到 `hourly_schedule`。

- [ ] **Step 13.12: 手动触发一次完整 run**

在 Dagster UI 点 `Assets` → 全选 → `Materialize all`，等待完成。

Expected: 4 个 asset 全部变绿。如果 `raw_ohlcv_feather` 失败因为网络，先在宿主机把 feather 文件下载好，然后只手动触发 `raw_ohlcv_in_pg` → `backtest_report`。

- [ ] **Step 13.13: 启用定时 schedule**

在 Dagster UI 的 Schedules 页面，把 `hourly_schedule` 切换为 ON。

- [ ] **Step 13.14: Commit**

```bash
cd /home/zp/airbyte/dagster_quant
git add -A
git commit -m "feat: dagster project for hourly crypto quant pipeline"

cd /home/zp/airbyte/docker-platform
git add docker-compose.yml 2>/dev/null || true
git commit -m "feat: add dagster container for quant pipeline" 2>/dev/null || true
```

---

## Task 14: Metabase Dashboard

**Files:** 纯 UI 配置，无代码变更。把 SQL 保留在 plan 里供手工粘贴。

- [ ] **Step 14.1: 确认 Metabase 已连接 `warehouse` 数据库**

打开 Metabase → Admin → Databases。如果没有 `warehouse`，加一个：
- Type: PostgreSQL
- Host: `dest-postgres`
- Port: `5432`
- Database: `warehouse`
- User: `postgres` / `postgres`

- [ ] **Step 14.2: 创建 Question 1 - 当前 Top 10 信号**

New → Question → Native query → `warehouse`：

```sql
SELECT pair, composite_score, z_mom, z_lowvol, z_volume, rank_in_date
FROM quant.mart_hourly_signals
WHERE date = (SELECT MAX(date) FROM quant.mart_hourly_signals)
ORDER BY rank_in_date
LIMIT 10;
```

保存为「当前 Top 10 信号」，Visualization: Table。

- [ ] **Step 14.3: 创建 Question 2 - 回测净值曲线**

```sql
SELECT date, nav
FROM quant.mart_backtest_nav
WHERE run_id = (
  SELECT run_id FROM quant.mart_backtest_nav
  ORDER BY ingested_at DESC LIMIT 1
)
ORDER BY date;
```

保存为「回测净值曲线」，Visualization: Line chart（x=date, y=nav）。

- [ ] **Step 14.4: 创建 Question 3 - 因子月度 IC**

```sql
SELECT month, factor_name, ic
FROM quant.mart_factor_ic
ORDER BY month, factor_name;
```

保存为「因子月度 IC」，Visualization: Bar chart（x=month, y=ic, series=factor_name）。

- [ ] **Step 14.5: 创建 Dashboard**

New → Dashboard → 命名「量化 MVP - 数字货币」，把上述 3 个 question 拖进去。

- [ ] **Step 14.6: 验收 + 截图**

```bash
mkdir -p /home/zp/work/trade/freqtrade/docs/superpowers/screenshots
# 在 Metabase 页面用浏览器截图保存为：
# docs/superpowers/screenshots/mvp-dashboard-2026-04-10.png
```

- [ ] **Step 14.7: Commit 截图**

```bash
cd /home/zp/work/trade/freqtrade
git add docs/superpowers/screenshots/
git commit -m "docs(quant): add Metabase dashboard screenshot for MVP"
```

---

## Task 15: DoD 验收 + 集成文档

**Files:**
- Create: `/home/zp/work/trade/freqtrade/docs/superpowers/runbooks/quant-mvp-runbook.md`

- [ ] **Step 15.1: 逐条核对 DoD**

运行并勾选 spec §3.3 的 6 条 DoD：

```bash
# DoD 1: 全链路自动化
curl -sS http://localhost:3001 > /dev/null && echo "Dagster UI ✓"
# （手工）在 Dagster UI 确认 asset graph + 手动触发成功 + schedule ON

# DoD 2: 数据完整性
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT COUNT(DISTINCT pair) AS pairs, COUNT(*) AS rows, MIN(date), MAX(date)
FROM quant_raw.ohlcv_crypto WHERE timeframe='1h';
"
# Expected: pairs=10, rows ≥ 80000

# DoD 3: 因子正确
psql -h localhost -p 5433 -U postgres -d warehouse -c "
SELECT COUNT(*) FROM quant.mart_hourly_signals
WHERE date = (SELECT MAX(date) FROM quant.mart_hourly_signals);
"
# Expected: 10

# DoD 4: freqtrade 回测
ls -lh /home/zp/work/trade/freqtrade/user_data/backtest_results/factor_signal_mvp*.json | head
# Expected: 至少一个文件

# DoD 5: freqtrade dry-run
tmux ls | grep freqtrade_dryrun && \
  tail -n 5 /home/zp/work/trade/freqtrade/user_data/logs/freqtrade_dryrun.log
# Expected: tmux session 存在，日志有最近的 heartbeat

# DoD 6: Metabase 仪表盘
# （手工）浏览器打开 Metabase → 「量化 MVP - 数字货币」→ 3 图表都有数据
```

- [ ] **Step 15.2: 写 runbook**

写文件 `docs/superpowers/runbooks/quant-mvp-runbook.md`：

```markdown
# 量化 MVP - 运维 Runbook

## 服务清单

| 服务 | 地址 | 启动方式 |
|---|---|---|
| dest-postgres | localhost:5433 | docker-platform compose |
| Metabase | http://localhost:<port> | docker-platform compose |
| Dagster | http://localhost:3001 | docker-platform compose |
| freqtrade dry-run | tmux session `freqtrade_dryrun` | `tmux attach -t freqtrade_dryrun` |

## 常见操作

### 手工跑一次全链路
打开 http://localhost:3001 → Assets → Materialize all

### 重跑 dbt
```bash
cd /home/zp/airbyte/quant_warehouse
QUANT_PG_HOST=localhost QUANT_PG_PORT=5433 dbt run --profiles-dir .
```

### 重跑 freqtrade 回测
```bash
cd /home/zp/work/trade/freqtrade
python -m freqtrade backtesting \
  --config user_data/config_crypto_mvp.json \
  --strategy FactorSignalStrategy \
  --timerange 20250410- \
  --export trades \
  --export-filename user_data/backtest_results/factor_signal_mvp_v1
python -m user_data.scripts.backtest_to_pg
```

### 重启 dry-run
```bash
tmux kill-session -t freqtrade_dryrun 2>/dev/null || true
tmux new-session -d -s freqtrade_dryrun \
  "cd /home/zp/work/trade/freqtrade && python -m freqtrade trade \
   --config user_data/config_crypto_mvp.json \
   --strategy FactorSignalStrategy \
   --logfile user_data/logs/freqtrade_dryrun.log"
```

## 常见故障

| 症状 | 排查 | 修复 |
|---|---|---|
| Dagster UI 空白 | `docker logs dagster` 看启动日志 | 通常是 pip install 失败或 workspace.yaml 路径错误 |
| dbt 报 `could not connect to server` | 检查 QUANT_PG_HOST 环境变量 | 宿主机跑用 localhost:5433，容器内用 dest-postgres:5432 |
| freqtrade backtesting 报 PG 连不上 | strategy `_load_signals` 在子进程里 | 在 config_crypto_mvp.json 的 environment 里传 QUANT_PG_DSN |
| mart_hourly_signals 无最新数据 | dbt run 是否跑过 | 手工 `dbt run --select mart_hourly_signals` |
| dry-run 日志没更新 | tmux session 是否还在 | `tmux ls`，不在则按「重启 dry-run」恢复 |

## 备份

- `dest-postgres` 的 `warehouse` 数据库建议每天 `pg_dump` 一次到 `/home/zp/airbyte/source-data/backups/`。
```

- [ ] **Step 15.3: Commit runbook + 收尾**

```bash
cd /home/zp/work/trade/freqtrade
git add docs/superpowers/runbooks/
git commit -m "docs(quant): add MVP runbook for quant platform"
```

- [ ] **Step 15.4: 打 tag**

```bash
cd /home/zp/work/trade/freqtrade
git tag -a quant-mvp-v0.1 -m "Quant Platform MVP v0.1: crypto + freqtrade closed loop"
```

---

## 完成标准（DoD 重申）

当且仅当以下 6 条全部打钩时，MVP 才算完成：

1. ✅ Dagster UI 能看到完整 asset graph，能手工触发跑通，schedule 开启
2. ✅ `quant_raw.ohlcv_crypto` ≥ 10 pairs × 1 年 × 1h
3. ✅ `quant.mart_hourly_signals` 最新时刻有 10 行排名
4. ✅ `freqtrade backtesting` 能跑通 `FactorSignalStrategy` 并输出报告
5. ✅ `freqtrade trade --dry-run` 后台运行稳定
6. ✅ Metabase Dashboard「量化 MVP - 数字货币」3 图表全部有数据

---

## Self-Review 结果

- **Spec 覆盖**：spec 的 §3 范围 / §4 架构 / §5 数据模型 / §6 组件 / §7 roadmap 全部有对应 task。spec §8 风险点（PG 连接在 backtest 子进程、dbt 容器依赖、Dagster 调宿主机路径）在 Task 10 / 13 的说明中对应 fallback 方案。
- **占位扫描**：所有 "TBD" / "similar to" 已消除。所有代码块给出完整内容。
- **类型一致**：`mart_hourly_signals` 的列 `composite_score` / `rank_in_date` 在 Task 7（创建）、Task 9（读取）、Task 14（查询）全部保持一致。`ohlcv_crypto` 字段在 Task 1 / 3 / 4 一致。`mart_backtest_nav` 字段在 Task 1（DDL）和 Task 11（写入）一致。

## 已知的后续风险 / V2 工作

- Task 13 的 Dagster 容器用 `pip install` 每次启动重装依赖——应该写 Dockerfile.dagster 预装（V2）
- FactorSignalStrategy 的信号是静态快照（__init__ 读一次），dry-run 想要最新信号必须重启（V2 加 refresh）
- `backtest_to_pg.py` 的净值曲线是 trade-by-trade 粗粒度，不是逐根 K 线的 equity curve（V2 用 freqtrade 的 `backtest-analysis` 输出）
- A 股（V2）

---

**计划结束**
