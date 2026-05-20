# DeepSeek QuantTrader v4.0 — AI 交易闭环系统

**版本**: v4.0 (大版本升级)  
**日期**: 2026-05-11  
**状态**: 设计阶段  

> 核心升级: 增加 AI 交易员工，形成"自动回测→模拟交易→人工审核→策略改进"双闭环

---

## 一、愿景

```
                    ┌──────────────────────────────┐
                    │     AI 交易员工 (Agent)        │
                    │  分析市场 → 生成策略 → 改进     │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
    ┌──────────┐           ┌──────────────┐          ┌──────────┐
    │ 因子分析  │           │  新闻情绪     │          │ 宏观研判  │
    │ (25因子)  │           │  (RSS+AI)    │          │ (17指标)  │
    └──────────┘           └──────────────┘          └──────────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │       策略生成引擎              │
                    │  因子组合 × 权重 × 过滤条件     │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
    ╔══════════════╗      ╔══════════════════╗      ╔══════════════╗
    ║  Loop 1      ║      ║    Loop 2        ║      ║   最终目标    ║
    ║  自动回测     ║ ───► ║   模拟交易        ║ ───► ║   实盘交易    ║
    ║  (无人值守)   ║      ║  (人工审核)       ║      ║  (可选)      ║
    ╚══════════════╝      ╚══════════════════╝      ╚══════════════╝
```

---

## 二、双闭环架构

### Loop 1: 自动回测闭环 (全自动)

```
┌─────────────────────────────────────────────────────────┐
│                    LOOP 1 — 自动回测                      │
│                                                         │
│  ① AI 生成策略                                           │
│     AI 交易员分析当前市场 → 生成 Top 5 策略               │
│     每策略 = 因子组合 + 权重 + 入场/出场规则               │
│                         │                               │
│                         ▼                               │
│  ② 自动回测                                              │
│     freqtrade backtesting --timerange 近一周              │
│     5 策略 × 10 币对 = 50 次回测 (并行)                   │
│                         │                               │
│                         ▼                               │
│  ③ 策略排名                                              │
│     ┌────────┬────────┬────────┬────────┬────────┐     │
│     │ Sharpe │ 胜率   │ 最大回撤│ 盈亏比 │ 综合分  │     │
│     ├────────┼────────┼────────┼────────┼────────┤     │
│     │ Strat1 │ 1.8    │ 62%    │ -8%    │ 2.1    │ 92  │
│     │ Strat2 │ 1.2    │ 55%    │ -12%   │ 1.8    │ 78  │
│     │ ...    │        │        │        │        │    │
│     └────────┴────────┴────────┴────────┴────────┘     │
│                         │                               │
│                         ▼                               │
│  ④ AI 分析报告                                           │
│     AI 读取回测结果 → 分析强弱项 → 输出改进建议            │
│                         │                               │
│                         ▼                               │
│  ⑤ 策略改进                                              │
│     AI 根据分析调整因子权重/规则 → 下一轮                │
│     └─────────────── 循环 ─────────────────┘             │
│                                                         │
│  频率: 每日/每周自动运行                                   │
└─────────────────────────────────────────────────────────┘
```

### Loop 2: 模拟交易闭环 (人工审核 + 自动监控)

```
┌─────────────────────────────────────────────────────────┐
│                    LOOP 2 — 模拟交易                      │
│                                                         │
│  ① 策略推荐                                              │
│     Loop 1 回测排名 Top 3 → 推荐进入模拟交易              │
│                         │                               │
│                         ▼                               │
│  ② 人工审核 ⚡                                            │
│     ┌─────────────────────────────────────┐             │
│     │ 交易员审核面板:                       │             │
│     │  • 回测摘要 (Sharpe/胜率/回撤)        │             │
│     │  • 策略参数 (因子/权重/规则)          │             │
│     │  • AI 分析报告                       │             │
│     │  • [ 批准 ] [ 修改 ] [ 拒绝 ]        │             │
│     └─────────────────────────────────────┘             │
│                         │                               │
│                         ▼                               │
│  ③ 启动模拟交易                                          │
│     freqtrade trade --dry-run                           │
│     虚拟资金: 10,000 USDT                                │
│     跟随真实市场行情                                      │
│                         │                               │
│                         ▼                               │
│  ④ 实时监控                                              │
│     ┌─────────────────────────────────────┐             │
│     │ 交易台 Dashboard:                    │             │
│     │  • 当前持仓 + 盈亏                   │             │
│     │  • 交易节点 (K线标注买卖点)           │             │
│     │  • AI 实时评论                       │             │
│     └─────────────────────────────────────┘             │
│                         │                               │
│                         ▼                               │
│  ⑤ 每日报告                                              │
│     AI 自动生成每日交易报告:                              │
│     • 当日交易汇总 (开/平/盈亏)                           │
│     • vs 基准对比 (BTC buy&hold)                         │
│     • 策略表现分析                                       │
│     • 改进建议                                           │
│                         │                               │
│                         ▼                               │
│  ⑥ 策略迭代                                              │
│     根据模拟结果 → 调整策略 → 重新回测验证                │
│     └─────────────── 循环 ─────────────────┘             │
│                                                         │
│  最终: 持续盈利策略 → 投入实盘                             │
└─────────────────────────────────────────────────────────┘
```

---

## 三、AI 交易员工 — 核心角色定义

```yaml
角色: AI 交易员 (ai-trader)
─────────────────────────
职责:
  1. 市场分析: 综合因子/新闻/宏观, 输出市场状态评估
  2. 策略生成: 根据市场状态, 生成候选交易策略
  3. 策略排名: 对回测结果排序, 推荐最优策略
  4. 交易监控: 监控模拟交易, 标注异常, 给出评论
  5. 日报生成: 每日输出交易日报 + 改进建议

能力:
  ✅ 读取 25 因子 (Factor MCP)
  ✅ 读取 17 宏观指标 (PostgreSQL)
  ✅ 读取新闻情感 (PostgreSQL)
  ✅ 分析回测结果 (JSON 解析)
  ✅ 分析交易记录 (PostgreSQL)
  ✅ 输出结构化策略 (JSON Schema)
  ✅ 输出分析报告 (Markdown)

约束:
  ❌ 不直接执行交易 (必须人工批准)
  ❌ 不访问资金/API Key
  ❌ 所有建议附带置信度和推理链
```

---

## 四、数据库设计

### 新增表

```sql
-- 策略定义表
CREATE TABLE quant.trade_strategies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version INT DEFAULT 1,
    status TEXT DEFAULT 'draft',  -- draft/backtesting/recommended/approved/active/archived
    created_by TEXT DEFAULT 'ai-trader',
    
    -- 策略参数
    factor_weights JSONB,         -- {"z_mom24": 0.3, "z_rsi14": 0.2, ...}
    entry_rules JSONB,            -- [{"factor": "composite_score", "op": ">", "value": 0.5}]
    exit_rules JSONB,
    stop_loss_pct NUMERIC(5,4),
    take_profit_pct NUMERIC(5,4),
    max_position_pct NUMERIC(5,4),
    pairs TEXT[],                 -- 交易币对列表
    
    -- 元数据
    market_context JSONB,         -- 生成时的市场状态
    ai_reasoning TEXT,            -- AI 生成理由
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 回测结果表
CREATE TABLE quant.backtest_results (
    id SERIAL PRIMARY KEY,
    strategy_id INT REFERENCES quant.trade_strategies(id),
    run_at TIMESTAMPTZ DEFAULT NOW(),
    timerange_start DATE,
    timerange_end DATE,
    
    -- 核心指标
    total_trades INT,
    win_rate NUMERIC(5,2),
    profit_factor NUMERIC(8,4),
    sharpe_ratio NUMERIC(6,2),
    max_drawdown_pct NUMERIC(5,2),
    total_return_pct NUMERIC(6,2),
    avg_trade_duration_hours NUMERIC(8,2),
    
    -- 详细数据
    pair_results JSONB,           -- 每个币对的详细结果
    trade_list JSONB,             -- 每笔交易的进出记录
    equity_curve JSONB,           -- 净值曲线 [[date, value], ...]
    
    -- AI 分析
    ai_analysis TEXT,             -- AI 对本次回测的分析
    ai_rank_score INT,            -- AI 综合排名分 (0-100)
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 模拟交易记录表
CREATE TABLE quant.paper_trades (
    id SERIAL PRIMARY KEY,
    strategy_id INT REFERENCES quant.trade_strategies(id),
    pair TEXT NOT NULL,
    
    -- 交易信息
    direction TEXT NOT NULL,       -- long / short
    entry_price NUMERIC(20,8),
    exit_price NUMERIC(20,8),
    amount NUMERIC(20,8),
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ,
    
    -- 结果
    pnl NUMERIC(20,8),
    pnl_pct NUMERIC(8,4),
    exit_reason TEXT,              -- stop_loss / take_profit / signal / manual
    
    -- AI 注释
    ai_entry_reasoning TEXT,
    ai_exit_comment TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 每日交易报告
CREATE TABLE quant.daily_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    strategy_id INT REFERENCES quant.trade_strategies(id),
    
    -- 报告内容
    summary TEXT,                  -- AI 生成的当日总结
    performance JSONB,             -- {pnl, trades, win_rate, ...}
    vs_benchmark JSONB,            -- vs BTC buy&hold
    issues JSONB,                  -- 发现的问题
    improvements JSONB,            -- 改进建议
    risk_flags JSONB,              -- 风险标记
    
    ai_generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 策略审核记录
CREATE TABLE quant.strategy_approvals (
    id SERIAL PRIMARY KEY,
    strategy_id INT REFERENCES quant.trade_strategies(id),
    action TEXT NOT NULL,          -- approve / reject / modify
    reviewer TEXT DEFAULT 'quant',
    comments TEXT,
    modified_params JSONB,         -- 如果修改, 记录修改内容
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 五、API 端点设计

### 策略管理

| 端点 | 方法 | 功能 |
|------|------|------|
| `/trade/strategies` | GET | 策略列表 (含状态筛选) |
| `/trade/strategies` | POST | AI 生成新策略 |
| `/trade/strategies/{id}` | GET | 策略详情 |
| `/trade/strategies/{id}` | PUT | 修改策略参数 |
| `/trade/strategies/{id}/approve` | POST | 人工批准策略 |
| `/trade/strategies/{id}/reject` | POST | 拒绝策略 |

### 回测

| 端点 | 方法 | 功能 |
|------|------|------|
| `/trade/backtest` | POST | 触发回测 (指定策略/时间范围) |
| `/trade/backtest/auto` | POST | 自动回测 (Top 5 策略, 近一周) |
| `/trade/backtest/{id}` | GET | 回测结果详情 |
| `/trade/backtest/rank` | GET | 策略排名 |

### 模拟交易

| 端点 | 方法 | 功能 |
|------|------|------|
| `/trade/paper/start` | POST | 启动模拟交易 |
| `/trade/paper/stop` | POST | 停止模拟交易 |
| `/trade/paper/status` | GET | 当前状态 (持仓/盈亏) |
| `/trade/paper/trades` | GET | 交易历史 |
| `/trade/paper/nodes` | GET | 交易节点 (K线标注) |

### 报告

| 端点 | 方法 | 功能 |
|------|------|------|
| `/trade/reports/daily` | GET | 每日交易报告 |
| `/trade/reports/daily/generate` | POST | AI 生成今日报告 |
| `/trade/reports/weekly` | GET | 周报 |

---

## 六、前端设计 — 三个新 Tab

### Tab 7: 策略实验室 (Strategy Lab)

```
┌─────────────────────────────────────────────────────────┐
│  🧪 策略实验室                                           │
│                                                         │
│  ┌─────────────────────┐  ┌───────────────────────────┐ │
│  │  AI 策略生成器       │  │  策略列表                   │ │
│  │                     │  │                           │ │
│  │ [ 自动分析市场 ]    │  │  Strat1  Sharpe 1.8  92分 │ │
│  │ [ 生成 Top 5 策略 ] │  │  Strat2  Sharpe 1.2  78分 │ │
│  │                     │  │  Strat3  Sharpe 0.9  65分 │ │
│  └─────────────────────┘  └───────────────────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  策略对比雷达图                 回测指标表             │ │
│  │  (Sharpe/胜率/回撤/盈亏比)     (可排序/筛选)         │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  AI 分析报告                                         │ │
│  │  "Strat1 在趋势行情表现优异, 但震荡市需优化..."       │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Tab 8: 交易台 (Trading Desk)

```
┌─────────────────────────────────────────────────────────┐
│  💹 交易台                                              │
│                                                         │
│  ┌──────────┬──────────┬──────────┬──────────┐         │
│  │ 总盈亏    │ 胜率     │ 持仓数    │ 可用资金  │         │
│  │ +$234.50 │ 62%      │ 2/3      │ $8,450   │         │
│  │ 🟢 +2.3% │          │          │          │         │
│  └──────────┴──────────┴──────────┴──────────┘         │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  当前持仓                                            │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │ BTC/USDT  多头  +$180  🟢  AI: 动量强劲      │   │ │
│  │  │ ETH/USDT  多头  +$54   🟢  AI: 跟随BTC      │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  交易节点图 (K线 + 买卖标注)                          │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │  ████████░░░░░░░░                             │   │ │
│  │  │  ██░░████░░░░░░  ● buy  ● sell               │   │ │
│  │  │  ░░████░░████░░                               │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  交易历史 (可筛选/导出)                               │ │
│  │  时间      │ 币对    │ 方向 │ 盈亏  │ AI 理由        │ │
│  │  05-11 08:00│BTC/USDT│ BUY  │ +$180 │ 动量+宏观     │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Tab 9: 交易报告 (Reports)

```
┌─────────────────────────────────────────────────────────┐
│  📊 交易报告                                            │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  日报  2026-05-11                                    │ │
│  │  ─────────────────                                  │ │
│  │  今日交易: 3 笔 (2赢 1亏)                             │ │
│  │  日盈亏: +$234.50 (+2.3%)                            │ │
│  │  累计盈亏: +$1,245.80 (+12.4%)                       │ │
│  │  vs BTC: +3.2% (跑赢)                                │ │
│  │                                                     │ │
│  │  AI 总结:                                            │ │
│  │  "今日策略表现良好, BTC多头获利$180。                 │ │
│  │   唯一亏损来自ETH短线回调, 建议增加RSI过滤..."        │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  净值曲线 (累计)                                      │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │         ░░░░░░░███                             │   │ │
│  │  │    ░░░░░░█████████                             │   │ │
│  │  │ ░░░░███████████████  — 策略                    │   │ │
│  │  │ ░░░░░░░░░░░████████  — BTC基准                  │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  改进建议                                            │ │
│  │  • 震荡市过滤: 增加 ADX > 25 条件                    │ │
│  │  • 止损优化: 建议从 5% 调至 3%                        │ │
│  │  • 增加 ETH/BTC 配对交易                              │ │
│  │  [ 采纳建议 ] [ 修改参数 ] [ 忽略 ]                   │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## 七、核心流程编排

### Loop 1: 自动回测 (定时任务)

```python
# cron: 每日 02:00 UTC
async def daily_auto_backtest():
    """Loop 1: 自动回测闭环"""
    
    # 1. AI 分析当前市场状态
    market_state = ai_trader.analyze_market()
    # → {regime: "trending", risk: "medium", top_factors: [...]}
    
    # 2. AI 生成 Top 5 策略
    strategies = ai_trader.generate_strategies(market_state, count=5)
    
    # 3. 并行回测近一周数据
    results = []
    for strat in strategies:
        result = freqtrade_backtest(
            strategy=strat,
            timerange="20260504-20260511",
            pairs=strat.pairs
        )
        results.append(result)
    
    # 4. AI 排名 + 分析
    rankings = ai_trader.rank_strategies(results)
    analysis = ai_trader.analyze_results(rankings)
    
    # 5. 保存结果 → 通知用户
    save_to_db(rankings, analysis)
    notify("Top 3 策略已更新, 请审核")
```

### Loop 2: 模拟交易 (人工触发)

```python
# 用户点击 "批准策略" 后
async def start_paper_trading(strategy_id: int):
    """Loop 2: 启动模拟交易"""
    
    # 1. 获取批准策略
    strat = get_approved_strategy(strategy_id)
    
    # 2. 生成 freqtrade 策略文件
    write_strategy_file(strat)
    
    # 3. 启动 dry-run
    # freqtrade trade --dry-run --strategy Strat1
    start_freqtrade_dry_run(strat)
    
    # 4. 启动监控
    start_monitor(strat.id)
    # - 每小时检查持仓状态
    # - 记录每笔交易
    # - AI 给出实时评论
```

### 每日报告生成

```python
# cron: 每日 08:00 UTC
async def daily_report():
    """生成每日交易报告"""
    
    for active_strat in get_active_strategies():
        # 1. 获取当日交易
        trades = get_today_trades(active_strat.id)
        
        # 2. AI 分析交易表现
        report = ai_trader.generate_daily_report(
            strategy=active_strat,
            trades=trades,
            market_state=get_current_market_state()
        )
        
        # 3. 保存报告
        save_report(report)
        
        # 4. 推送给用户
        notify_user(report.summary)
```

---

## 八、开发计划 (v4.0)

### Sprint 8: 策略生成 + 回测 (3天)

| # | 任务 | 产出 |
|---|------|------|
| 8.1 | AI 策略生成器 (`/trade/strategies` POST) | AI 输出结构化策略 JSON |
| 8.2 | 自动回测引擎 (freqtrade wrapper) | 并行回测 Top 5 |
| 8.3 | 回测结果解析 + 存储 | `backtest_results` 表 |
| 8.4 | AI 策略排名 + 分析报告 | 排名算法 + Markdown 报告 |
| 8.5 | 前端: 策略实验室 Tab | 策略列表/对比/排名 |

### Sprint 9: 模拟交易 + 监控 (2天)

| # | 任务 | 产出 |
|---|------|------|
| 9.1 | 人工审核流程 | 批准/修改/拒绝 |
| 9.2 | freqtrade dry-run 管理 | 启动/停止/状态查询 |
| 9.3 | 交易记录采集 | `paper_trades` 表 |
| 9.4 | 前端: 交易台 Tab | 持仓/盈亏/交易节点 |

### Sprint 10: 报告 + 闭环 (2天)

| # | 任务 | 产出 |
|---|------|------|
| 10.1 | 每日报告生成 | AI 日报 |
| 10.2 | 净值曲线 + 基准对比 | 可视化 |
| 10.3 | AI 改进建议 | 策略迭代 |
| 10.4 | 前端: 报告 Tab | 日报/周报/改进面板 |

### Sprint 11: 测试 + 文档 (1天)

| # | 任务 |
|---|------|
| 11.1 | 单元测试 (回测/交易/报告) |
| 11.2 | 端到端测试 (完整闭环) |
| 11.3 | 用户手册 |

---

## 九、技术架构总览

```
┌──────────────────────────────────────────────────────────┐
│                     Vue Dashboard (:25173)                │
│  ┌──────────┬──────────┬──────────┬──────────────────┐  │
│  │ 因子研究  │ AI分析   │ 策略实验室│ 交易台 │ 报告    │  │
│  │ (现有)   │ (现有)   │ ⭐新增   │ ⭐新增 │ ⭐新增  │  │
│  └──────────┴──────────┴──────────┴──────────────────┘  │
├──────────────────────────────────────────────────────────┤
│                  API Server (:20080)                      │
│  ┌───────────────────────────────────────────────────┐  │
│  │  api_quant.py (现有)    │  api_trade.py ⭐新增    │  │
│  │  /quant/chat            │  /trade/strategies      │  │
│  │  /quant/skills          │  /trade/backtest        │  │
│  │  /quant/sync/*          │  /trade/paper/*         │  │
│  │  /quant/factors         │  /trade/reports/*       │  │
│  └───────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│                     MCP Servers                           │
│  ┌──────────────────┐  ┌──────────────────────────────┐ │
│  │ Factor MCP :29010│  │ AI Trader Agent (P3 enhanced)│ │
│  │ 5 tools          │  │ analyze / generate / rank    │ │
│  └──────────────────┘  │ report / monitor / improve   │ │
│                        └──────────────────────────────┘ │
├──────────────────────────────────────────────────────────┤
│                     PostgreSQL (:5433)                    │
│  quant.trade_strategies    quant.backtest_results        │
│  quant.paper_trades        quant.daily_reports           │
│  quant.strategy_approvals  ( + 现有表 )                  │
├──────────────────────────────────────────────────────────┤
│                     freqtrade                             │
│  backtesting (自动回测)    trade --dry-run (模拟交易)     │
└──────────────────────────────────────────────────────────┘
```

---

## 十、关键指标

| 指标 | 目标 |
|------|------|
| 策略生成频率 | 每日 5 个 |
| 回测覆盖 | 近 7 天 × 10 币对 |
| 回测速度 | < 5 分钟 (并行) |
| 模拟资金 | 10,000 USDT |
| 最大持仓 | 3 |
| 每日报告时间 | 08:00 UTC |
| 策略审批时间 | < 24h |
| 闭环周期 | 1 周 (生成→回测→模拟→改进) |
