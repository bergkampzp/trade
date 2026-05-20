# Metabase 量化 MVP Dashboard 手工配置

这份 runbook 把 `quant.*` schema 里的三张 mart 表串成一个 Metabase dashboard。
所有底层数据已经在 `warehouse` 数据库里就绪（见文末"数据状态核验"节）。

## 前置条件

- Metabase 容器正在 `http://localhost:3000` 运行
- `metabase` 与 `dest-postgres` 在同一个 docker 网络（已验证：`dest-postgres` 可在 metabase 容器里通过 DNS 解析）
- 已有 Metabase 管理员账号

## Step 1: 把 `warehouse` 加为数据源（约 2 分钟）

1. 访问 `http://localhost:3000`，以管理员身份登录
2. 右上角齿轮 → **Admin settings** → **Databases** → **Add database**
3. 填写：
   - **Database type**: PostgreSQL
   - **Display name**: `quant_warehouse`
   - **Host**: `dest-postgres`   ← 注意是容器名，不是 localhost
   - **Port**: `5432`             ← 容器内端口，不是宿主机 5433
   - **Database name**: `warehouse`
   - **Username**: `postgres`
   - **Password**: `postgres`
   - **Schemas**: 留空 = 全部，或填 `quant,quant_raw`
4. 点 **Save**，等 Metabase 扫描完成（10-30 秒）
5. 回到 Admin → Databases，确认 `quant_warehouse` 状态是 **Sync finished**

**如果连接失败**：`docker exec metabase bash -c 'getent hosts dest-postgres'` 确认 DNS；
再 `docker exec metabase bash -c 'nc -vz dest-postgres 5432'` 确认 TCP 可达。

## Step 2: 创建三个 Question（Native SQL）

Metabase 左侧 **+ New → SQL query**，数据库选 `quant_warehouse`。

### Question 1: "最新 Top 10 信号"

```sql
SELECT
    pair,
    composite_score::numeric(10, 3) AS score,
    rank_in_date AS rank
FROM quant.mart_hourly_signals
WHERE date = (SELECT MAX(date) FROM quant.mart_hourly_signals)
ORDER BY rank_in_date
LIMIT 10;
```

- **Visualization**: Table
- **Save as**: `最新 Top 10 信号`
- 期望结果：AVAX 排 1、ETH 排 10（见"数据状态核验"）

### Question 2: "回测 NAV 曲线"

```sql
SELECT
    date::date AS day,
    nav::numeric(12, 2) AS nav
FROM quant.mart_backtest_nav
WHERE run_id = (
    SELECT run_id
    FROM quant.mart_backtest_nav
    ORDER BY date DESC
    LIMIT 1
)
ORDER BY date;
```

- **Visualization**: Line chart
  - X-axis: `day`
  - Y-axis: `nav`
- **Save as**: `回测 NAV 曲线 (FactorSignalStrategy)`
- 期望：365 个点，起点 ~10002，终点 ~9739，最高 ~10085

### Question 3: "月度因子 IC"

```sql
SELECT
    month::date AS month,
    factor_name,
    ic::numeric(6, 4) AS ic
FROM quant.mart_factor_ic
ORDER BY month, factor_name;
```

- **Visualization**: Bar chart
  - X-axis: `month`
  - Y-axis: `ic`
  - **Series breakout**: `factor_name`（三因子分色）
- **Save as**: `月度因子 IC`
- 期望：13 个月 × 3 个因子 = 39 根柱子，IC 范围 ±0.035

## Step 3: 组装 Dashboard

1. 左侧 **+ New → Dashboard**
2. **Name**: `量化 MVP - 数字货币`
3. 依次把三个 Question 拖进来：
   - 上方：`回测 NAV 曲线` 占满一行
   - 下方左：`最新 Top 10 信号`
   - 下方右：`月度因子 IC`
4. 点 **Save**

完成后的 URL 类似 `http://localhost:3000/dashboard/N-量化-mvp-数字货币`。

## 数据状态核验（2026-04-10）

跑以下 SQL 应该看到这些数字，如果不符说明哪一层缺数据：

```sql
-- 原始 OHLCV
SELECT COUNT(*), MIN(date), MAX(date) FROM quant_raw.ohlcv_crypto;
-- 期望: 87630, 2025-04-10, 2026-04-10

-- 信号 mart
SELECT COUNT(*) FROM quant.mart_hourly_signals;
-- 期望: 87390

-- NAV
SELECT COUNT(*), MIN(nav)::numeric(10,2), MAX(nav)::numeric(10,2)
FROM quant.mart_backtest_nav;
-- 期望: 365, 9732.37, 10085.42

-- IC
SELECT COUNT(*) FROM quant.mart_factor_ic;
-- 期望: 39
```

## 重跑数据的快速命令（worktree 根目录下）

```bash
# 1. 同步 feather → PG（如果 freqtrade 新下载了数据）
.venv/bin/python user_data/scripts/feather_to_pg.py

# 2. 重建所有 dbt 模型
cd /home/zp/airbyte/quant_warehouse && dbt run

# 3. 重跑回测
.venv/bin/freqtrade backtesting \
    --config user_data/config_crypto_mvp.json \
    --strategy FactorSignalStrategy \
    --timerange 20250411-

# 4. 把最新 JSON 写回 PG（脚本会自动用文件名做 run_id，幂等 upsert）
.venv/bin/python user_data/scripts/backtest_to_pg.py \
    $(ls -t user_data/backtest_results/backtest-result-*.json | head -1)
```

Metabase 的 question 在下次 dashboard 刷新时会自动读到新数据，无需重建。
