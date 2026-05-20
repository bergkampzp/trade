# Sprint 3: 宏观经济因子 + 自动多因子组合 — 设计文档

## Context

Sprint 1+2 已完成：10 pair × 1h OHLCV → dbt 14 技术因子 → 三级评估漏斗 → scoreboard → Vue Dashboard。Sprint 3 的目标是引入宏观经济数据作为新因子，并构建自动多因子组合策略，验证宏观因子是否为 crypto 1h 交易提供增量 alpha。

## 设计决策

| 决策 | 选择 |
|------|------|
| Sprint 主线 | 宏观经济 + 因子筛选优化 |
| 宏观定位 | 宏观作为新因子（进入 3-tier 评估管线） |
| 数据来源 | FRED 经济指标 + FinBERT 新闻情绪 |
| 筛选优化 | 自动多因子组合构建（Equal Weight + IC-Weighted） |
| 交付目标 | 研究验证完成（回测结果 + Dashboard 展示） |
| 架构方案 | 宏观先行：数据管线 → 因子 → 评估 → 组合 → Dashboard |

---

## Section 1: 宏观数据管线

### 数据源与指标

**FRED 经济指标**（通过 fredapi 拉取，免费 API key）:

| 指标 | FRED Series | 频率 | 对 Crypto 的逻辑 |
|------|-------------|------|------------------|
| CPI YoY | CPIAUCSL | 月 | 通胀上升 → 避险/风险资产分化 |
| 联邦基金利率 | FEDFUNDS | 月 | 加息 → 流动性收紧 → crypto 压力 |
| 10Y-2Y 利差 | T10Y2Y | 日 | 倒挂 → 衰退预期 → risk-off |
| VIX | VIXCLS | 日 | 恐慌指数 → crypto 与美股联动 |
| 美元指数 DXY | DTWEXBGS | 日 | 美元走强 → crypto 承压 |
| PMI | ISM/PMI | 月 | 经济景气度指标 |

**FinBERT 新闻情绪**:
- 数据源：CryptoNews API / RSS feeds（CoinDesk, CoinTelegraph, Bloomberg Crypto）
- 模型：`ProsusAI/finbert` (HuggingFace)，CPU 推理即可
- 聚合：每小时聚合为 sentiment_score（均值）和 sentiment_volume（文章数）

### 数据管线架构

```
FRED API (fredapi)  ──→  quant_raw.macro_indicators (PG)
    │                         │
    │ 月/日频                  │ dbt: forward-fill to 1h
    │                         ↓
    │                    quant.int_macro_hourly
    │
CryptoNews RSS ──→ FinBERT ──→ quant_raw.news_sentiment (PG)
    │                         │
    │ 实时/每小时              │ dbt: hourly aggregation
    │                         ↓
    │                    quant.int_sentiment_hourly
    │
    └─────────────────────────→ quant.feat_macro_* (z-score 因子)
```

### 频率对齐策略

- **月度指标**（CPI, FEDFUNDS, PMI）: forward-fill（发布后不变，直到下次发布）
- **日度指标**（VIX, DXY, T10Y2Y）: 在当日所有小时复制同一值
- **对齐后统一 z-score**: 滚动 720h (30d) 窗口，与技术因子保持一致

### PG DDL

```sql
CREATE TABLE quant_raw.macro_indicators (
    series_id   TEXT NOT NULL,
    date        TIMESTAMPTZ NOT NULL,
    value       NUMERIC NOT NULL,
    PRIMARY KEY (series_id, date)
);

CREATE TABLE quant_raw.news_sentiment (
    id          SERIAL PRIMARY KEY,
    published_at TIMESTAMPTZ NOT NULL,
    source      TEXT,
    headline    TEXT NOT NULL,
    sentiment   TEXT NOT NULL,
    score       NUMERIC NOT NULL,
    raw_scores  JSONB
);
```

### 数据拉取脚本

- `user_data/scripts/fetch_fred.py` — fredapi 拉取 6 指标，upsert 到 PG
- `user_data/scripts/fetch_news_sentiment.py` — RSS 抓取 + FinBERT 推理 + 写入 PG

---

## Section 2: 宏观因子工程

### 产出因子（Bucket B: Macro Factors）

| 因子名 | z-score 列 | 方向 | 来源 | 逻辑 |
|--------|-----------|------|------|------|
| `cpi_yoy` | z_cpi | negative | FRED | CPI 上升 → risk-off |
| `fed_rate` | z_fedrate | negative | FRED | 加息 → 流动性紧缩 |
| `yield_spread` | z_yldspd | positive | FRED | 利差扩大 → 经济健康 |
| `vix` | z_vix | negative | FRED | VIX 升高 → 恐慌 |
| `dxy` | z_dxy | negative | FRED | 美元走强 → crypto 承压 |
| `pmi` | z_pmi | positive | FRED | PMI > 50 → 扩张 |
| `news_sentiment` | z_newssent | positive | FinBERT | 正面情绪 → 看多 |
| `news_volume` | z_newsvol | negative | FinBERT | 异常多新闻 → 波动加剧 |

共 **8 个宏观因子** + 现有 14 技术因子 = **22 因子候选池**。

### dbt 模型

```
models/
├── intermediate/
│   ├── int_macro_hourly.sql        -- FRED 指标 forward-fill 到 1h
│   └── int_sentiment_hourly.sql    -- 新闻情绪按小时聚合
├── features/
│   ├── feat_cpi_yoy.sql            -- 各宏观因子 720h z-score
│   ├── feat_fed_rate.sql
│   ├── feat_yield_spread.sql
│   ├── feat_vix.sql
│   ├── feat_dxy.sql
│   ├── feat_pmi.sql
│   ├── feat_news_sentiment.sql
│   └── feat_news_volume.sql
```

每个 feature 模型：JOIN int_*_hourly 与 stg_ohlcv_crypto → 720h rolling z-score → 输出 (pair, date, raw_value, z_score)

### factors.yml 扩展

在现有 factors.yml 中添加 Bucket B（8 个宏观因子），格式与 Bucket A/C 一致。

### mart_hourly_signals 扩展

新增 8 列 z-score 列，composite_score 暂保持等权。

---

## Section 3: 自动多因子组合构建

### 组合构建流程

```
22 因子候选池
      │
      ▼
 Tier 1-2 筛选 → 通过的因子（预估 8-12 个）
      │
      ▼
 相关性过滤 → 去掉高相关因子（|corr| > 0.7 取 IC 更高的）
      │          预估剩余 5-8 个
      ▼
 权重计算 → 2 种方法对比
   ├── Equal Weight（等权基线）
   └── IC-Weighted（按 IC IR 加权）
      │
      ▼
 组合信号 → composite_zscore = Σ(w_i × z_i)
      │
      ▼
 组合策略回测 → freqtrade backtest
   Entry: composite_zscore > threshold AND rank ≤ N
   Exit:  composite_zscore < exit_threshold OR rank > M
      │
      ▼
 结果对比 → 单因子 vs EW vs IC-W
             Sharpe / MaxDD / 年化收益 / 交易次数
```

### 实现组件

**1. portfolio_builder.py** (`user_data/scripts/portfolio_builder.py`)
- 输入：factors.yml + scoreboard + mart_factor_ic_extended
- 相关性过滤：贪心选择低相关高 IC 因子
- Equal Weight: w_i = 1/N
- IC-Weighted: w_i = |ic_ir_i| / Σ|ic_ir|
- 输出：`quant.mart_portfolio_weights`

**2. mart_composite_signal.sql** (`models/mart/mart_composite_signal.sql`)
- 读取权重 + mart_hourly_signals → composite_zscore = Σ(w_i × z_i)

**3. CompositeStrategy.py** (`user_data/strategies/CompositeStrategy.py`)
- 继承 FactorSignalStrategy，使用 composite_zscore

**4. run_composite_backtest.py** (`user_data/scripts/run_composite_backtest.py`)
- EW / IC-W 分别回测，结果写入 `quant.mart_composite_backtest`

---

## Section 4: API 扩展 + Dashboard 集成

### 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/quant/macro-indicators` | GET | 宏观指标时间序列 |
| `/quant/portfolio-weights` | GET | 组合权重 |
| `/quant/composite-backtest` | GET | 组合回测对比 |
| `/quant/composite-nav` | GET | 组合 NAV 曲线 |
| `/quant/composite-trades` | GET | 组合交易标注 |

### Dashboard 新增组件

- 因子列表增加 Bucket B（Macro）标签
- 新增「组合」Tab：EW / IC-W Sharpe 对比
- K 线图支持 composite_zscore 叠加
- 组合概览：权重饼图 + Sharpe 对比柱状图 + NAV 曲线

---

## Section 5: 实施分期

| Phase | 内容 | 预计周末 |
|-------|------|----------|
| **Phase 1** | 宏观数据管线：DDL + fredapi + FinBERT + dbt 对齐 | 周末 1 |
| **Phase 2** | 宏观因子工程：8 个 feat_* + factors.yml + signals 扩展 | 周末 2 前半 |
| **Phase 3** | 全量评估：22 因子 3-tier + scoreboard | 周末 2 后半 |
| **Phase 4** | 组合构建：builder + signal + strategy + 回测 | 周末 3 |
| **Phase 5** | API + Dashboard + 端到端验证 | 周末 4 |

---

## 验收标准

1. FRED 6 指标 + FinBERT 情绪数据在 PG 中，1h 对齐完成
2. 22 因子 3-tier 评估结果在 scoreboard
3. EW / IC-W 两种组合策略回测结果（Sharpe, MaxDD, 收益率）
4. Dashboard 展示宏观因子 + 组合权重 + 组合 NAV 对比
5. 研究结论：宏观因子是否为 crypto 1h 交易提供增量 alpha

## 技术栈（新增）

| 组件 | 选择 | 理由 |
|------|------|------|
| FRED 数据 | fredapi | 标准 Python FRED 客户端，免费 |
| 新闻情绪 | ProsusAI/finbert | 金融 BERT，CPU 可用 |
| 新闻源 | CryptoNews RSS | 免费 |
| 组合优化 | numpy | EW + IC-W 无需 scipy |

## YAGNI

- Mean-Variance 权重优化
- ML 因子提取
- Dagster 调度
- 实盘 / dry-run
- 链上数据因子
- 多资产类别
- HMM 体制检测
- FinGPT 深度分析
