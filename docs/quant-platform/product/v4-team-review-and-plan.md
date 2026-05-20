# DeepSeek QuantTrader v4.0 — 团队评审综合报告 + 开发计划

**评审日期**: 2026-05-11  
**评审角色**: 产品经理 · 项目经理 · 算法工程师 · 技术架构师  
**结论**: ⚠️ **条件通过** — 方案方向正确，需补齐 5 项关键设计后可启动开发

---

## 一、各角色评审结论

| 角色 | 结论 | 核心意见 |
|------|:---:|------|
| 产品经理 | ⚠️ 条件通过 | 缺用户故事+验收标准，产品化程度需提升 |
| 项目经理 | ⚠️ 条件通过 | 排期偏紧(8→11天)，单人开发风险高 |
| 算法工程师 | ⚠️ 条件通过 | 缺过拟合防护+样本外验证，策略可信度存疑 |
| 技术架构师 | ⚠️ 条件通过 | 进程管理+安全设计需补充，4项Blocking问题 |

---

## 二、共识与分歧

### 共识（四角色一致）

1. **双闭环架构方向正确** — Loop1(自动回测)+Loop2(模拟交易)是量化交易的成熟范式
2. **freqtrade 复用合理** — 不造轮子，利用现有的 backtesting/dry-run 能力
3. **AI 角色约束到位** — 不直接执行交易、人工审核关卡是必要的安全设计
4. **文档细节不足以直接开发** — 需补充用户故事、验收标准、安全方案

### 关键分歧

| 问题 | 产品经理 | 项目经理 | 算法 | 架构 |
|------|---------|---------|------|------|
| 排期 | 8天可试 | 8天不足→11天 | 算法迭代需额外时间 | 需加0.5天安全设计 |
| 策略过拟合 | — | — | 高风险，必须加验证层 | 支持算法建议 |
| 进程管理 | — | 需 supervisor | — | 推荐 systemd 模板 |
| 数据库设计 | — | — | — | 缺索引+版本管理 |

**决议**: 采纳项目经理的 11 天排期，在 Sprint 8 前补 0.5 天设计，采纳算法过拟合防护方案，采纳技术架构的安全建议。

---

## 三、必须解决的关键问题 (Blocking)

| # | 问题 | 来源 | 解决方案 |
|---|------|------|------|
| B1 | **缺用户故事+验收标准** | 产品 | 补充 8 个 User Story，定义 AC |
| B2 | **无过拟合防护** | 算法 | 因子≤8个 + 样本外回测 + Deflated Sharpe |
| B3 | **无样本外验证层** | 算法 | 回测窗口: 训练60% + 验证20% + 测试20% |
| B4 | **进程管理方案缺失** | 架构 | systemd 模板单元管理 dry-run |
| B5 | **AI 命令注入风险** | 架构 | Jinja2模板生成 + JSON Schema校验 + ast.parse |

---

## 四、更新后的开发计划 v4.0

### 总工期: 11.5 天 (含 0.5 天设计补齐)

```
Day 0.5  ██ 设计补齐
          ├─ 补充 8 个 User Story + Acceptance Criteria
          ├─ 更新数据库 Schema (索引+版本管理+唯一约束)
          ├─ 确定进程管理方案 (systemd 模板)
          └─ 补充安全设计 (命令注入防护/rate limit)

Sprint 8 ██████ 策略生成 + 回测引擎 (3天)
Day 1-3  ├─ 数据库 migration (5张表+索引)
          ├─ api_trade.py — /trade/strategies CRUD + Pydantic schema
          ├─ AI 策略生成器 (temperature=0, 因子≤8)
          ├─ freqtrade backtesting wrapper (subprocess + 超时+错误处理)
          ├─ 回测结果解析器 (parse freqtrade backtesting JSON)
          ├─ AI 策略排名 (Deflated Sharpe + 综合评分)
          └─ 前端: 策略实验室 Tab

Sprint 9 ██████ 模拟交易 + 监控 (2.5天)
Day 4-6  ├─ 人工审核流程 (approve/reject/modify + audit log)
          ├─ freqtrade strategy file 生成器 (Jinja2 template)
          ├─ dry-run 进程管理 (systemd service 模板)
          ├─ 交易记录采集 (freqtrade REST API → paper_trades)
          ├─ K线交易节点标注 API (/trade/paper/nodes)
          └─ 前端: 交易台 Tab

Sprint 10 ████ 报告 + 闭环 (2天)
Day 7-9  ├─ AI 每日交易报告 (cron 08:00 UTC)
          ├─ 净值曲线 + vs BTC 基准对比
          ├─ AI 改进建议 → 策略迭代触发
          ├─ /trade/reports/* API
          └─ 前端: 报告 Tab

Sprint 11 ██████ 测试 + 安全加固 + 文档 (3天)
Day 9-11 ├─ 单元测试 (策略CRUD/回测/交易/报告)
          ├─ 安全加固 (rate limit + 命令注入防护 + CORS)
          ├─ 端到端闭环测试 (生成→回测→审核→模拟→报告)
          ├─ 错误场景测试 (回测失败/爆仓/进程崩溃)
          └─ 用户手册 + API 文档
```

### 里程碑

| 日期 | 里程碑 | 验收标准 |
|------|--------|------|
| D+0.5 | 设计补齐完成 | US+AC 文档就绪，DB schema 定稿 |
| D+3.5 | Sprint 8 完成 | AI 可生成策略+自动回测+排名 |
| D+6 | Sprint 9 完成 | 模拟交易可启动+监控 |
| D+8 | Sprint 10 完成 | 日报自动生成 |
| D+11 | Sprint 11 完成 | 全闭环测试通过，可发布 |

---

## 五、新增用户故事 (P0 — 必须)

| # | 用户故事 | 验收标准 |
|---|---------|------|
| US-1 | 作为量化交易员，我希望 AI 自动分析当前市场并生成 Top 5 候选策略，以便快速筛选有潜力的交易思路 | 点击"生成策略"后 < 60s 内返回 5 个策略，每个含因子权重+入场规则+AI 理由 |
| US-2 | 作为交易员，我希望回测候选策略的一周表现，并看到排名，以便选择最优策略 | 排名表含 Sharpe/胜率/回撤/盈亏比，标注入选/淘汰原因 |
| US-3 | 作为交易员，我希望审核 AI 推荐的策略，批准后才进入模拟，以便控制风险 | 审核面板展示回测摘要+策略参数，支持 批准/修改/拒绝 三种操作 |
| US-4 | 作为交易员，我希望实时查看模拟交易的持仓和盈亏，并在 K 线上看到买卖点，以便判断策略效果 | 交易台显示持仓列表+盈亏+交易节点标注，5秒内刷新 |
| US-5 | 作为交易员，我希望每日收到 AI 生成的交易报告，包含 vs BTC 基准对比和改进建议，以便持续优化 | 每日 08:00 自动生成报告，含净值曲线+归因分析+改进清单 |
| US-6 | 作为交易员，当策略回测失败或模拟爆仓时，我希望及时收到通知，以便止损 | 异常事件 < 5 分钟内通知 (Dashboard 红色标记) |
| US-7 | 作为交易员，我希望修改策略参数（因子权重/止损/止盈）并重新回测，以便迭代优化 | PUT 修改参数 → 自动触发重新回测 → 显示新旧对比 |
| US-8 | 作为交易员，我希望查看策略的历史版本和对应的回测/模拟结果，以便追溯决策依据 | 策略详情页含版本历史+关联回测/交易记录 |

---

## 六、更新后的数据库 Schema (含索引)

```sql
-- 策略版本分离
CREATE TABLE quant.trade_strategies (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    created_by TEXT DEFAULT 'ai-trader',
    current_version_id INT,  -- 指向最新版本
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE quant.trade_strategy_versions (
    id SERIAL PRIMARY KEY,
    strategy_id INT REFERENCES quant.trade_strategies(id),
    version INT NOT NULL,
    factor_weights JSONB,
    entry_rules JSONB,
    exit_rules JSONB,
    stop_loss_pct NUMERIC(5,4),
    take_profit_pct NUMERIC(5,4),
    max_position_pct NUMERIC(5,4),
    pairs TEXT[],
    market_context JSONB,
    ai_reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_id, version)
);
CREATE INDEX idx_strategy_versions_sid ON quant.trade_strategy_versions(strategy_id, version DESC);

-- 回测结果
CREATE TABLE quant.backtest_results (
    id SERIAL PRIMARY KEY,
    strategy_version_id INT REFERENCES quant.trade_strategy_versions(id),
    run_at TIMESTAMPTZ DEFAULT NOW(),
    timerange_start DATE,
    timerange_end DATE,
    total_trades INT,
    win_rate NUMERIC(5,2),
    profit_factor NUMERIC(8,4),
    sharpe_ratio NUMERIC(6,2),
    max_drawdown_pct NUMERIC(5,2),
    total_return_pct NUMERIC(6,2),
    avg_trade_duration_hours NUMERIC(8,2),
    pair_results JSONB,
    trade_list JSONB,
    equity_curve JSONB,
    ai_analysis TEXT,
    ai_rank_score INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_backtest_results_svid ON quant.backtest_results(strategy_version_id, run_at DESC);
CREATE INDEX idx_backtest_results_score ON quant.backtest_results(ai_rank_score DESC);

-- 模拟交易
CREATE TABLE quant.paper_trades (
    id SERIAL PRIMARY KEY,
    strategy_version_id INT REFERENCES quant.trade_strategy_versions(id),
    trade_id TEXT,  -- freqtrade trade ID
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price NUMERIC(20,8),
    exit_price NUMERIC(20,8),
    amount NUMERIC(20,8),
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ,
    pnl NUMERIC(20,8),
    pnl_pct NUMERIC(8,4),
    exit_reason TEXT,
    ai_entry_reasoning TEXT,
    ai_exit_comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_version_id, trade_id)
);
CREATE INDEX idx_paper_trades_svid_time ON quant.paper_trades(strategy_version_id, entry_time);

-- 每日报告
CREATE TABLE quant.daily_reports (
    id SERIAL PRIMARY KEY,
    strategy_version_id INT REFERENCES quant.trade_strategy_versions(id),
    report_date DATE NOT NULL,
    summary TEXT,
    performance JSONB,
    vs_benchmark JSONB,
    issues JSONB,
    improvements JSONB,
    risk_flags JSONB,
    ai_generated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_version_id, report_date)
);

-- 审核记录
CREATE TABLE quant.strategy_approvals (
    id SERIAL PRIMARY KEY,
    strategy_version_id INT REFERENCES quant.trade_strategy_versions(id),
    action TEXT NOT NULL,
    reviewer TEXT DEFAULT 'quant',
    comments TEXT,
    modified_params JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_approvals_svid ON quant.strategy_approvals(strategy_version_id);
```

---

## 七、安全加固清单

| # | 措施 | 实现方式 |
|---|------|------|
| S1 | 命令注入防护 | Jinja2 模板生成策略文件 + JSON Schema 校验 + ast.parse |
| S2 | API rate limit | slowapi：AI生成≤10次/天，回测≤5次/天 |
| S3 | 数据库密码 | 统一从 `QUANT_PG_DSN` 环境变量读取 |
| S4 | dry-run 隔离 | systemd 模板单元，每人策略一个 service |
| S5 | 审核授权 | `/trade/strategies/{id}/approve` 要求 JWT 认证 |
| S6 | API Key 保护 | `chmod 600 ~/.hermes/config.yaml` |

---

## 八、算法防护清单

| # | 措施 | 说明 |
|---|------|------|
| A1 | 因子数限制 ≤8 | 从25因子中选Top8（IC最强），降低过拟合 |
| A2 | 样本外验证 | 回测窗口按 60/20/20 拆分 (训练/验证/测试) |
| A3 | Deflated Sharpe Ratio | 替代简单排名，校正多重比较 |
| A4 | temperature=0 | 保证策略生成可复现 |
| A5 | 贝叶斯优化替代LLM调参 | 中期优化，首版用网格搜索 |

---

## 九、归档

| 文档 | 路径 |
|------|------|
| v4.0 交易闭环设计 | `product-design-v4-trading.md` |
| 产品评审报告 | `~/.hermes/v4-trading-product-review.md` |
| 项目管理评审 | `~/.hermes/pm-review-v4-trading.md` |
| 算法评审报告 | `~/.hermes/ALGORITHM_REVIEW_QuantTrader_v4.md` |
| 技术架构评审 | (内嵌于综合报告中) |
| 团队综合报告+开发计划 | 本文档 |

---

**最终结论**: ⚠️ 条件通过。补齐 5 项 Blocking 设计后可启动 Sprint 8 (D+0.5)。预计 D+11 完成全部开发+测试。
