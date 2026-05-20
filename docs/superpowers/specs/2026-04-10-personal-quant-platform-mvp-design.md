# 个人量化研究平台 设计文档（v3）

- **状态**：v3 Released — Sprint 1 + Sprint 2 已完成
- **作者**：PM (主导) + 产品经理 / 技术 agent / 算法工程师 / 后台工程师 / 数据库工程师
- **创建日期**：2026-04-10
- **修订历史**：
  - v1 (2026-04-10): A 股 + vectorbt 方案
  - v2 (2026-04-10): 改为数字货币 + freqtrade 方案，端到端打通链路
  - v3 (2026-04-10): Sprint 1+2 完成，新增因子研究闭环，14 因子 + 三级漏斗评估系统

---

## 1. 产品概述

### 1.1 是什么

一个**个人加密量化研究平台**，把现有数据栈（PostgreSQL + dbt + Metabase）与 freqtrade 交易框架打通，实现从行情采集 → 因子建模 → 自动评估 → 回测验证 → 可视化的**完整闭环**。

### 1.2 核心能力

| 能力 | Sprint 1 | Sprint 2 | 状态 |
|------|----------|----------|------|
| 行情数据采集（10 对 × 1h） | ✅ | ✅ | 完成 |
| BTC 3 年历史数据 | - | ✅ | 完成 |
| dbt 因子计算（3 因子） | ✅ | ✅ 扩展到 14 因子 | 完成 |
| 综合信号排名 | ✅ | ✅ | 完成 |
| freqtrade 回测 | ✅ | ✅ 支持单因子模式 | 完成 |
| 回测 NAV 写入 PG | ✅ | ✅ | 完成 |
| Metabase 仪表盘 | ✅ MVP 面板 | ✅ 因子研究面板 | 完成 |
| **因子研究闭环** | - | ✅ 三级漏斗自动评估 | **新增** |
| **IC 分析** | ✅ 月度 IC | ✅ 多窗口 IC + 滚动 3M | 升级 |
| **分位数回测** | - | ✅ 纯 SQL 年化 Sharpe | **新增** |
| **因子相关性矩阵** | - | ✅ pairwise Pearson | **新增** |
| **因子评分板** | - | ✅ mart_factor_scoreboard | **新增** |
| dry-run 模拟交易 | 🔜 计划中 | - | Sprint 3 |
| Dagster 定时调度 | 🔜 计划中 | - | Sprint 3 |

### 1.3 非目标（明确排除）

- ❌ A 股 / 美股 / 港股 / 期货
- ❌ ML 模型（LightGBM / sklearn）— 只做线性 IC
- ❌ 实盘下单（只跑 dry_run 模式）
- ❌ 多交易所（只用 Binance）
- ❌ 分钟级高频
- ❌ 组合优化（Markowitz / risk parity / Kelly）
- ❌ 链上数据因子（funding rate / MVRV）— Sprint 3
- ❌ 多 timeframe — 只做 1h

---

## 2. 技术架构

### 2.1 系统架构图

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    个人量化研究平台（Sprint 2 架构）                       │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  【数据源】 Binance（via CCXT，freqtrade 封装）                           │
│         │                                                                │
│         ▼                                                                │
│  【采集层】 freqtrade download-data                                       │
│    → 10 pair × 1h × 1 年 (BTC 扩展到 3 年)                               │
│    → feather 文件 → feather_to_pg.py → PG                                │
│         │                                                                │
│         ▼                                                                │
│  【数仓层】 PostgreSQL (localhost:5433, warehouse DB)                      │
│    ├─ quant_raw.ohlcv_crypto        原始 OHLCV (PK: pair+tf+date)        │
│    ├─ quant.dim_accepted_factors    已接受因子集 (Sprint 2 新增)           │
│    └─ quant.mart_factor_scoreboard  因子评分板 (Sprint 2 新增)            │
│         │                                                                │
│         ▼                                                                │
│  【建模层】 dbt-core 1.11 + dbt-postgres 1.10                            │
│    项目: /home/zp/airbyte/quant_warehouse/                               │
│    ┌─────────────────────────────────────────────────────────┐            │
│    │ staging/   stg_ohlcv_crypto (view)                     │            │
│    │ inter./    int_hourly_returns (table)                   │            │
│    │ features/  14 个 feat_*.sql (table)                     │   ← SP2   │
│    │ mart/      mart_hourly_signals (table, 14 z-score 列)  │   ← SP2   │
│    │            mart_factor_values_long (view, UNPIVOT)      │   ← SP2   │
│    │            mart_factor_ic_extended (table)              │   ← SP2   │
│    │            mart_factor_ic_rolling (table)               │   ← SP2   │
│    │            mart_factor_quantile_backtest (table)        │   ← SP2   │
│    │            mart_factor_correlation (table)              │   ← SP2   │
│    │            mart_factor_ic (table, Sprint 1)             │            │
│    │            mart_backtest_nav (external, Python 写入)     │            │
│    └─────────────────────────────────────────────────────────┘            │
│         │                           │                                    │
│         ▼                           ▼                                    │
│  【研究闭环】                  【执行层】                                  │
│  run_research_loop.py         FactorSignalStrategy                       │
│  ┌────────────────────┐       ├─ 默认模式: 3 因子 composite              │
│  │ Phase 1: 加载注册表  │       └─ 单因子模式: QUANT_FACTOR_NAME 环境变量  │  ← SP2
│  │ Phase 2: dbt 刷新   │              │                                  │
│  │ Phase 3: Tier 1 IC  │              ▼                                  │
│  │ Phase 4: Tier 2     │       freqtrade backtesting                     │
│  │  分位数 + 相关性    │       → backtest_to_pg.py → PG                   │
│  │ Phase 5: Tier 3     │                                                 │
│  │  freqtrade 回测    │                                                 │
│  │ Phase 6: Scoreboard │                                                 │
│  │ Phase 7: 报告       │                                                 │
│  └────────────────────┘                                                  │
│         │                                                                │
│         ▼                                                                │
│  【可视化层】 Metabase (localhost:3000)                                    │
│    ├─ Dashboard 1: "量化 MVP" (Sprint 1)                                 │
│    └─ Dashboard 2: "因子研究闭环" (Sprint 2, 6 张卡片)                    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 组件清单

| 组件 | 类型 | 路径 | 说明 |
|------|------|------|------|
| freqtrade | ♻️ 复用 | `/home/zp/work/trade/freqtrade/` | 数据采集 + 回测 + 策略执行引擎 |
| PostgreSQL 15 | ♻️ 复用 | `localhost:5433` / `dest-postgres:5432` | 数仓 (warehouse DB) |
| Metabase | ♻️ 复用 | `localhost:3000` | BI 可视化 |
| dbt project | 🆕 SP1 | `/home/zp/airbyte/quant_warehouse/` | 因子建模 |
| feather_to_pg.py | 🆕 SP1 | `user_data/scripts/` | feather → PG 数据桥 |
| backtest_to_pg.py | 🆕 SP1 | `user_data/scripts/` | 回测 NAV → PG |
| FactorSignalStrategy | 🆕 SP1, 改 SP2 | `user_data/strategies/` | freqtrade 策略 |
| run_research_loop.py | 🆕 SP2 | `user_data/scripts/` | 因子研究闭环 orchestrator |
| factor_registry.py | 🆕 SP2 | `user_data/scripts/` | factors.yml 加载器 |
| factors.yml | 🆕 SP2 | `user_data/` | 14 因子注册表 |
| run_single_factor_backtest.py | 🆕 SP2 | `user_data/scripts/` | 单因子回测封装 |
| compute_correlation_filter.py | 🆕 SP2 | `user_data/scripts/` | Tier 2 相关性过滤 |

### 2.3 技术栈

| 层 | 技术 | 版本 |
|----|------|------|
| 数据采集 | freqtrade + CCXT | freqtrade 2025.3-dev, CCXT 4.4.69 |
| 数据存储 | PostgreSQL | 15 |
| 数据建模 | dbt-core + dbt-postgres | 1.11.7 + 1.10.0 |
| 策略回测 | freqtrade backtesting | 内置 |
| 编程语言 | Python | 3.12 |
| 可视化 | Metabase | (复用现有) |
| 代码质量 | ruff + mypy + flake8 | pre-commit hooks |

---

## 3. 数据模型

### 3.1 原始数据层 (`quant_raw`)

#### `ohlcv_crypto`

| 字段 | 类型 | 说明 |
|------|------|------|
| pair | VARCHAR(20) | 如 `BTC/USDT` |
| timeframe | VARCHAR(5) | `1h` |
| date | TIMESTAMPTZ | K 线起始时间 (UTC) |
| open / high / low / close | NUMERIC(20,8) | OHLC 价格 |
| volume | NUMERIC(30,8) | 成交量 |
| ingested_at | TIMESTAMPTZ | 同步时间 |

**PK**: `(pair, timeframe, date)` | **数据量**: 105,151 行 (含 BTC 3 年)

### 3.2 dbt 分层模型 (`quant` schema)

```
stg_ohlcv_crypto (view)
  └── int_hourly_returns (table: pair, date, close, volume, prev_close, ret_1h)
        ├── feat_momentum_24h         ┐
        ├── feat_momentum_7d          │
        ├── feat_momentum_30d         │
        ├── feat_reversal_1h          │
        ├── feat_reversal_24h         │
        ├── feat_volatility_24h       │  14 个因子
        ├── feat_lowvol_7d            │  (Sprint 2)
        ├── feat_rsi_14               │
        ├── feat_bollinger_pos_24h    │
        ├── feat_volume_zscore_24h    │
        ├── feat_amihud_24h           │
        ├── feat_garman_klass_24h     │
        ├── feat_vol_price_diverge... │
        └── feat_mfi_14               ┘
              └── mart_hourly_signals (14 z-score 列 + composite + rank)
                    └── mart_factor_values_long (UNPIVOT view)
                          ├── mart_factor_ic_extended (IC 多窗口)
                          ├── mart_factor_ic_rolling (滚动 3M IC)
                          ├── mart_factor_quantile_backtest (分位数回测)
                          └── mart_factor_correlation (因子相关性)
```

### 3.3 Python 写入表

| 表 | 写入方 | PK | 说明 |
|----|--------|-----|------|
| `mart_backtest_nav` | backtest_to_pg.py | (run_id, date) | 回测 NAV 曲线 |
| `mart_factor_scoreboard` | run_research_loop.py | (factor_name, run_date) | 因子评分板 |
| `dim_accepted_factors` | 手动 INSERT | (factor_name) | 已接受因子集 |

### 3.4 数据覆盖

| 品种 | 时间范围 | 行数 | 频率 |
|------|----------|------|------|
| BTC/USDT | 2023-04-11 → 2026-04-10 | 26,284 | 1h |
| ETH/USDT 等 9 个 | 2025-04-10 → 2026-04-10 | 各 8,763 | 1h |
| **总计** | | **105,151** | |

---

## 4. 因子体系

### 4.1 因子列表（14 个）

| # | 因子 | Bucket | 类型 | 方向 | 计算逻辑 | Sprint |
|---|------|--------|------|------|----------|--------|
| 1 | momentum_24h | A | 动量 | + | close/close_24h - 1 | SP1 |
| 2 | lowvol_24h | A | 波动 | − | 24h 滚动 stddev(ret_1h) | SP1 |
| 3 | volume_zscore_24h | A | 量能 | + | 24h 量 z-score vs 30d | SP1 |
| 4 | momentum_7d | A | 动量 | + | close/close_168h - 1 | SP2 |
| 5 | momentum_30d | A | 动量 | + | close/close_720h - 1 | SP2 |
| 6 | reversal_1h | A | 反转 | + | −ret_1h | SP2 |
| 7 | reversal_24h | A | 反转 | + | −(close/close_24h - 1) | SP2 |
| 8 | lowvol_7d | A | 波动 | − | 168h 滚动 stddev | SP2 |
| 9 | rsi_14 | A | 强弱 | + | 14h RSI | SP2 |
| 10 | bollinger_pos_24h | A | 技术 | + | 布林带位置 [-1,1] | SP2 |
| 11 | amihud_24h | C | 流动性 | − | avg(\|ret\|/dollarVol) 24h | SP2 |
| 12 | garman_klass_24h | C | 波动 | − | GK 波动率 24h 均值 | SP2 |
| 13 | vol_price_divergence_24h | C | 微结构 | − | corr(ret, volChg) 24h | SP2 |
| 14 | mfi_14 | C | 资金流 | + | 14h Money Flow Index | SP2 |

**方向含义**：`+` = z-score 越高越看多，`−` = 原始值越低越好（z-score 时取反）

### 4.2 因子注册表

`user_data/factors.yml` 是所有因子的 single source of truth：

```yaml
factors:
  - name: momentum_24h
    bucket: A
    feature_model: feat_momentum_24h
    raw_column: momentum_24h
    zscore_column: z_mom24
    direction: positive
    description: "24h trailing return"
  # ... 共 14 条
```

**添加新因子的 3 步清单**：
1. 创建 `models/features/feat_<name>.sql`
2. 在 `factors.yml` 添加条目
3. 在 `mart_hourly_signals.sql` 添加 JOIN + z-score 列 + `mart_factor_values_long.sql` 添加 UNION ALL

---

## 5. 因子研究闭环（Sprint 2 核心功能）

### 5.1 三级漏斗评估

```
14 个候选因子
  │
  ▼ Tier 1：IC 过滤（纯 SQL，dbt 计算）
  │  |IC mean| ≥ 0.005 AND |IC IR| ≥ 0.3
  │
  5 个候选
  │
  ▼ Tier 2：分位数回测 + 相关性（纯 SQL，dbt 计算）
  │  年化 Sharpe(top−bottom) ≥ 0.8
  │  AND max|corr with accepted_factors| ≤ 0.7
  │
  4 个候选
  │
  ▼ Tier 3：freqtrade 全回测（subprocess，~5 秒/因子）
  │  Sharpe ≥ 1.0 AND MaxDD ≤ 15%
  │
  verdict: PASS / FAIL_TIER1 / FAIL_TIER2_SHARPE / FAIL_TIER2_CORR /
           FAIL_TIER3_SHARPE / FAIL_TIER3_DD / FAIL_TIER3_ERROR
```

### 5.2 研究闭环 Orchestrator

**入口**：`python user_data/scripts/run_research_loop.py`

| Phase | 内容 | 耗时 |
|-------|------|------|
| 1. 加载注册表 | 解析 factors.yml，过滤 `--factors` | <1s |
| 2. dbt 刷新 | `dbt run --select staging+ intermediate+ features+ mart_hourly_signals+` | ~5s |
| 3. Tier 1 IC | 读 mart_factor_ic_extended，过滤 | <1s |
| 4. Tier 2 分位数+相关性 | 读 mart_factor_quantile_backtest + mart_factor_correlation | <1s |
| 5. Tier 3 回测 | 逐个跑 freqtrade backtest subprocess | ~5s/因子 |
| 6. Scoreboard | UPSERT mart_factor_scoreboard | <1s |
| 7. 报告 | 生成 markdown + 输出到终端 | <1s |

**总耗时**：14 因子全量评估 ≈ 25-30 秒

### 5.3 CLI 用法

```bash
# 全量评估（含 dbt 刷新 + 回测）
python user_data/scripts/run_research_loop.py --factors all

# 跳过 dbt（数据已最新）
python user_data/scripts/run_research_loop.py --factors all --skip-dbt

# 只跑 Tier 1+2（跳过回测）
python user_data/scripts/run_research_loop.py --factors all --skip-tier3

# 评估指定因子
python user_data/scripts/run_research_loop.py --factors rsi_14,mfi_14

# 预览（不执行任何操作）
python user_data/scripts/run_research_loop.py --dry-run
```

### 5.4 单因子回测模式

`FactorSignalStrategy` 支持通过环境变量切换到单因子模式：

```bash
# 默认模式：使用 Sprint 1 的 3 因子 composite_score
freqtrade backtesting --config user_data/config_crypto_mvp.json \
    --strategy FactorSignalStrategy

# 单因子模式：用 rsi_14 的 z-score 作为排名依据
QUANT_FACTOR_NAME=rsi_14 freqtrade backtesting --config user_data/config_crypto_mvp.json \
    --strategy FactorSignalStrategy
```

**安全机制**：`QUANT_FACTOR_NAME` 的值必须在 `factors.yml` 注册表中存在，否则 `bot_start()` 抛出 ValueError。

---

## 6. Sprint 1 技术报告

### 6.1 完成内容

| 交付物 | 说明 |
|--------|------|
| `feather_to_pg.py` | 10 pair feather → PG UPSERT，支持增量 |
| `backtest_to_pg.py` | 回测 JSON → NAV 曲线写入 PG |
| `FactorSignalStrategy` | freqtrade 策略，bot_start() 从 PG 读信号 |
| dbt 项目 (5 模型) | stg → int → 3 feat → mart_hourly_signals + mart_factor_ic |
| Metabase 面板 | 3 张卡片：Top 10 信号 / 回测 NAV / 月度 IC |
| 单元测试 | 7 个策略测试 + 4 个 backtest_to_pg 测试 |

### 6.2 回测结果（Sprint 1 基线）

- **策略**：3 因子等权 composite → top-3 入场 → rank>5 出场
- **期间**：2025-04-11 → 2026-04-10（1 年）
- **交易**：560 笔
- **品种**：10 pair + BNB/USDT:USDT

### 6.3 已知问题（Code Review 标记）

| ID | 级别 | 问题 | 状态 |
|----|------|------|------|
| I1 | Important | mart_factor_ic 缺少 gap-safe LEAD | 🔜 |
| I2 | Important | backtest_to_pg date_str→TIMESTAMPTZ 隐式转换 | 🔜 |
| I3 | Important | populate_indicators 无陈旧信号告警 | 🔜 |
| I4 | Important | _signals_df 类属性模式可改进 | ✅ SP2 改为 bot_start 初始化 |
| I5 | Important | dbt 缺少 (pair,date) 唯一性测试 | 🔜 |

---

## 7. Sprint 2 技术报告

### 7.1 完成内容

| 交付物 | 文件数 | 说明 |
|--------|--------|------|
| Bucket A 因子 SQL | 7 | momentum_7d/30d, reversal_1h/24h, lowvol_7d, rsi_14, bollinger_pos |
| Bucket C 因子 SQL | 4 | amihud, garman_klass, vol_price_divergence, mfi |
| mart 分析模型 | 5 | values_long, ic_extended, ic_rolling, quantile_backtest, correlation |
| mart_hourly_signals 改造 | 1 | 14 z-score 列，保留 Sprint 1 composite |
| DDL (scoreboard + dim) | 1 | mart_factor_scoreboard + dim_accepted_factors |
| Python orchestrator | 4 | run_research_loop + factor_registry + corr_filter + single_backtest |
| 策略改造 | 1 | QUANT_FACTOR_NAME 单因子模式 |
| factors.yml | 1 | 14 因子注册表 |
| Metabase SQL | 1 | 6 张卡片查询 |
| 运行手册 | 1 | docs/sprint2_research_loop.md |

**dbt 模型总计**：23 个（staging 1 + intermediate 1 + features 14 + mart 7）

### 7.2 首次全量运行结果

```
Phase 1: 14 factors loaded
Phase 3 Tier 1: 5/14 passed → reversal_24h, momentum_24h, rsi_14, bollinger_pos_24h, vol_price_divergence_24h
Phase 4 Tier 2: 4/5 passed → momentum_24h, rsi_14, bollinger_pos_24h, vol_price_divergence_24h
                (reversal_24h 被淘汰: 与 momentum_24h corr=1.0)
Phase 5 Tier 3: 0/4 passed → 全部负 Sharpe
```

**因子 IC 排行**：

| 因子 | IC Mean | IC IR | 分位数 Sharpe | Tier 3 Sharpe |
|------|---------|-------|---------------|---------------|
| vol_price_divergence_24h | +0.0061 | 0.987 | +3.01 | −5.63 |
| reversal_24h | +0.0097 | 0.748 | +2.75 | (Tier 2 淘汰) |
| bollinger_pos_24h | −0.0076 | −1.051 | −3.17 | −18.10 |
| rsi_14 | −0.0054 | −0.936 | −3.20 | −14.46 |
| momentum_24h | −0.0097 | −0.748 | −3.32 | −10.04 |

### 7.3 结果解读

**Tier 3 全军覆没的原因分析**（@算法工程师）：

1. **因子方向不匹配**：momentum_24h、rsi_14、bollinger_pos_24h 的 IC 都是**负数**，意味着"高值 → 低未来收益"。但当前策略做多 top rank（高 z-score），方向反了。
2. **策略未区分正/反向因子**：`FactorSignalStrategy` 只有"做多 top rank"一种逻辑，没有根据因子 direction 翻转排序。
3. **这不是系统 bug，而是研究发现**：闭环正确地揭示了"24h 动量在加密市场 1h 频率上是反转信号"——这本身就是有价值的结论。

**Sprint 3 应对方案**：
- 在策略中根据 `factors.yml` 的 `direction` 字段翻转 `ORDER BY` 方向
- 对 IC 为负的因子，做多 bottom rank 而非 top rank
- 预期：vol_price_divergence_24h（IC 为正，分位数 Sharpe 3.01）最可能首个 PASS

### 7.4 性能数据

| 指标 | 数值 |
|------|------|
| dbt 全量刷新 (23 模型) | ~5 秒 |
| 单因子 freqtrade 回测 | ~5 秒 |
| 14 因子全流程（含 4 次回测） | ~25 秒 |
| mart_hourly_signals 行数 | 87,412 |
| mart_factor_values_long 行数 | ~1M (14 因子 × 87k) |
| mart_factor_correlation 行数 | 105 (14×15/2 上三角) |

---

## 8. 使用指南

### 8.1 环境准备

```bash
# 1. 确保 PostgreSQL 运行
psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -c "SELECT 1"

# 2. 确保 dbt 可用
dbt --version  # 期望 1.11.x

# 3. 确保 freqtrade venv 激活
/home/zp/work/trade/freqtrade/.venv/bin/freqtrade --version
```

### 8.2 日常操作

#### 更新数据

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp

# 下载最新 1h 数据（增量）
freqtrade download-data --config user_data/config_crypto_mvp.json \
    --timeframes 1h --days 7

# 同步到 PG
python -m user_data.scripts.feather_to_pg
```

#### 运行因子评估

```bash
# 全量评估
python user_data/scripts/run_research_loop.py --factors all

# 快速预览（跳过回测）
python user_data/scripts/run_research_loop.py --factors all --skip-dbt --skip-tier3
```

#### 查看结果

```bash
# 终端查看 scoreboard
psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" \
    -c "SELECT factor_name, verdict, ic_mean, quantile_sharpe
        FROM quant.mart_factor_scoreboard
        WHERE run_date = CURRENT_DATE ORDER BY verdict"

# Markdown 报告
cat /tmp/sprint2_report_$(date +%Y-%m-%d).md

# Metabase 面板
open http://localhost:3000
```

#### 添加新因子

见 §4.2 的 3 步清单 + 详细指南在 `docs/sprint2_research_loop.md`。

#### 祝福一个因子（加入已接受集）

```sql
INSERT INTO quant.dim_accepted_factors (factor_name, notes)
VALUES ('vol_price_divergence_24h', 'Sprint 2 首个候选');
```

### 8.3 freqtrade 回测

```bash
# Sprint 1 默认策略
freqtrade backtesting --config user_data/config_crypto_mvp.json \
    --strategy FactorSignalStrategy --timerange 20250411-20260410

# Sprint 2 单因子模式
QUANT_FACTOR_NAME=vol_price_divergence_24h \
    freqtrade backtesting --config user_data/config_crypto_mvp.json \
    --strategy FactorSignalStrategy --timerange 20250411-20260410
```

---

## 9. 文件目录结构

### freqtrade 仓库 (feature/quant-mvp 分支)

```
user_data/
├── config_crypto_mvp.json          # freqtrade 配置
├── factors.yml                     # 因子注册表 (SP2)
├── strategies/
│   └── factor_signal_strategy.py   # 策略 (SP1, SP2 改)
├── scripts/
│   ├── feather_to_pg.py           # feather → PG (SP1)
│   ├── backtest_to_pg.py          # 回测 → PG (SP1)
│   ├── run_research_loop.py       # 研究闭环 orchestrator (SP2)
│   ├── factor_registry.py         # 注册表加载器 (SP2)
│   ├── compute_correlation_filter.py  # Tier 2 相关性 (SP2)
│   └── run_single_factor_backtest.py  # 单因子回测 (SP2)
├── tests/
│   ├── test_factor_signal_strategy.py  # 7 个测试 (SP1)
│   └── test_backtest_to_pg.py          # 4 个测试 (SP1)
├── data/binance/
│   └── *.feather                  # 10 pair 历史数据
└── backtest_results/
    └── *.zip                      # 回测结果

docs/
├── sprint2_dashboard_queries.sql   # Metabase SQL (SP2)
├── sprint2_research_loop.md        # 运行手册 (SP2)
└── superpowers/
    ├── specs/
    │   └── 2026-04-10-...-design.md    # 本文档
    └── plans/
        └── 2026-04-10-...-impl.md      # 实施计划
```

### quant_warehouse 仓库

```
/home/zp/airbyte/quant_warehouse/
├── dbt_project.yml
├── profiles.yml
├── ddl/
│   ├── 001_quant_raw.sql
│   ├── 002_quant_mart.sql
│   └── 003_quant_scoreboard.sql     # SP2
├── models/
│   ├── staging/
│   │   └── stg_ohlcv_crypto.sql
│   ├── intermediate/
│   │   └── int_hourly_returns.sql
│   ├── features/                    # 14 个因子
│   │   ├── feat_momentum_24h.sql    (SP1)
│   │   ├── feat_volatility_24h.sql  (SP1)
│   │   ├── feat_volume_zscore_24h.sql (SP1)
│   │   ├── feat_momentum_7d.sql     (SP2)
│   │   ├── feat_momentum_30d.sql    (SP2)
│   │   ├── feat_reversal_1h.sql     (SP2)
│   │   ├── feat_reversal_24h.sql    (SP2)
│   │   ├── feat_lowvol_7d.sql       (SP2)
│   │   ├── feat_rsi_14.sql          (SP2)
│   │   ├── feat_bollinger_pos_24h.sql (SP2)
│   │   ├── feat_amihud_24h.sql      (SP2)
│   │   ├── feat_garman_klass_24h.sql (SP2)
│   │   ├── feat_vol_price_divergence_24h.sql (SP2)
│   │   └── feat_mfi_14.sql          (SP2)
│   └── mart/
│       ├── mart_hourly_signals.sql  (SP1, SP2 改)
│       ├── mart_factor_ic.sql       (SP1)
│       ├── mart_factor_values_long.sql     (SP2)
│       ├── mart_factor_ic_extended.sql     (SP2)
│       ├── mart_factor_ic_rolling.sql      (SP2)
│       ├── mart_factor_quantile_backtest.sql (SP2)
│       └── mart_factor_correlation.sql     (SP2)
└── .gitignore
```

---

## 10. Sprint 路线图

| Sprint | 目标 | 状态 |
|--------|------|------|
| **Sprint 1** | 端到端 MVP：数据采集 → dbt 3 因子 → freqtrade 回测 → Metabase 面板 | ✅ 完成 |
| **Sprint 2** | 因子研究闭环：14 因子 + 三级漏斗 + orchestrator + 评分板 | ✅ 完成 |
| **Sprint 3** | ① 因子方向修正（策略支持反向因子）② Bucket B 链上因子（funding rate / MVRV）③ BTC 3 年时序稳定性 ④ Dagster 定时调度 ⑤ dry-run 常驻 | 🔜 |
| **Sprint 4** | ① A 股接入 ② 多 timeframe ③ ML 因子（LightGBM） ④ 组合优化 | 📋 |

---

## 11. Metabase 面板

### Dashboard 1: 量化 MVP（Sprint 1）

3 张卡片：
1. Top 10 信号表格（最新时间点的 composite_score 排名）
2. 回测净值曲线（mart_backtest_nav）
3. 因子月度 IC 折线图（mart_factor_ic）

### Dashboard 2: 因子研究闭环（Sprint 2）

6 张卡片（SQL 见 `docs/sprint2_dashboard_queries.sql`）：
1. **Factor Scoreboard** — 最新运行的因子评分表，按 verdict 排序
2. **IC Heatmap** — factor × month 的 IC 热力图
3. **Correlation Matrix** — factor × factor 相关性矩阵
4. **Tier Progression Funnel** — 各级漏斗通过数
5. **Top Factor NAV Curves** — Tier 3 回测的净值曲线
6. **IC Stability** — 滚动 3M IC 稳定性折线图

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| IC 阈值过严/过松 | 所有因子被淘汰或全部通过 | 首次运行后根据分布调整，已从 0.015 调至 0.005 |
| Garman-Klass 数值不稳定 | high=low 时 ln(0) | SQL 中使用 NULLIF + GREATEST(1e-12) 保护 |
| 因子方向未翻转 | Tier 3 全部负 Sharpe | Sprint 3 首要修复：根据 direction 翻转排序 |
| freqtrade 子进程失败 | 无法完成 Tier 3 | stderr 捕获到 /tmp/sprint2_runs/，notes 字段记录 |
| mart_hourly_signals 向后兼容 | 改动破坏 Sprint 1 策略 | composite_score 定义不变，z_mom/z_lowvol 别名保留 |
| mart_factor_values_long 性能 | ~1M 行视图查询慢 | 实测秒级；如慢可改 materialized view |
