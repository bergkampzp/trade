# DeepSeek QuantTrader — 产品设计文档 v4.0

**更新日期**: 2026-05-11  
**版本**: v4.0 (大版本升级)  
**状态**: P0-P4 已完成，v4.0 交易闭环系统设计完成  

> v4.0 核心升级: AI 交易员工 → 自动回测闭环 + 模拟交易闭环 → 实盘就绪

---

## 一、项目定位

个人加密货币量化研究平台，核心能力：
- **数据引擎**: OpenBB FRED (17 指标) + freqtrade Binance (10 币对) + RSS 新闻
- **因子引擎**: dbt 模型 19 技术因子 + 6 宏观因子 → mart_hourly_signals
- **AI 分析**: DeepSeek Chat Agent v3，动态 MCP 工具发现 + 自适应多轮推理
- **Skills 系统**: 5 个量化分析 Skills，对标 Anthropic Fin SKILL.md 标准
- **可视化**: Vue 3 Dashboard，6 Tab（因子研究/宏观数据/经济新闻/AI分析/分析结论/数据同步）

---

## 二、系统全景架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                     🌐 用户浏览器 (:25173)                           │
│                                                                     │
│  ┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐    │
│  │ 因子研究 │ 宏观数据 │ 经济新闻 │⭐AI分析 │ 分析结论 │ 数据同步 │    │
│  │ K线+因子 │ 17指标  │ RSS情感 │ Skill↓ │ 综合面板 │ 4源状态  │    │
│  └────┬────┴────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘    │
└───────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┘
        │         │         │         │         │         │
        ▼         ▼         ▼         ▼         ▼         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   📡 Freqtrade API Server (:20080)                   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                      api_quant.py                             │  │
│  │                                                               │  │
│  │  /quant/sync/*     /quant/factors     /quant/chat  ⭐ P3+P4  │  │
│  │  ┌────────────┐   ┌──────────────┐   ┌───────────────────┐  │  │
│  │  │ news (async)│   │ data-sources │   │ _discover_mcp()   │  │  │
│  │  │ macro(async)│   │ factors      │   │ _load_skill()     │  │  │
│  │  │ crypto(async│   │ factor-zscore│   │ _call_llm() ×≤5   │  │  │
│  │  │ dbt         │   │ ohlcv        │   │ SSE streaming     │  │  │
│  │  └────────────┘   └──────────────┘   └───────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
        │                                     │
        ▼                                     ▼
┌───────────────────┐             ┌────────────────────────┐
│   🧠 MCP Servers   │             │   🤖 DeepSeek API      │
│                    │             │   (Function Calling)   │
│  Factor MCP :29010│             └────────────────────────┘
│  ├─ ranking (5)   │
│  ├─ zscore        │
│  ├─ correlation   │
│  ├─ signal        │
│  └─ macro         │
│                    │
│  OpenBB MCP :28001│
│  ├─ economy       │
│  └─ crypto        │
└────────┬───────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      🗄️ PostgreSQL (:5433)                          │
│                                                                     │
│  quant_raw.                   quant.                                │
│  ├─ ohlcv_crypto  112k       ├─ mart_hourly_signals  110k          │
│  ├─ macro_indicators 71k     ├─ mart_factor_values_long             │
│  ├─ news_sentiment  22       ├─ mart_factor_ic                      │
│  └─ sync_status / sync_log   ├─ mart_factor_correlation             │
│                              └─ mart_factor_scoreboard              │
└─────────────────────────────────────────────────────────────────────┘
         ▲                         ▲
         │                         │
┌────────┴────────┐    ┌───────────┴──────────┐
│  📊 数据采集层   │    │  🔄 数据转换层        │
│                 │    │                      │
│  OpenBB 4.7.1   │    │  dbt (34 models)     │
│  ├─ FRED (17)   │    │  原始 → 因子信号      │
│  └─ OECD (free) │    │  6 macro + 19 tech   │
│                 │    │  = 25 factors        │
│  freqtrade      │    └──────────────────────┘
│  └─ Binance (10)│
│                 │
│  feedparser     │
│  └─ RSS (3源)   │
└─────────────────┘
```

---

## 三、AI Agent 引擎流程 (P3+P4)

```
用户提问 ──────────────────────────────────────────────► 最终回答
  │                                                        ▲
  │  "分析BTC风险"                                          │
  ▼                                                        │
┌──────────────────────────────────────────────────────┐   │
│              POST /quant/chat v3                      │   │
│                                                      │   │
│  ① 解析请求: skill="risk-assessment", pair="BTC"     │   │
│                                                      │   │
│  ② 构建 System Prompt (Base + Skill + References)    │   │
│                                                      │   │
│  ③ 动态工具发现: _discover_mcp_tools()               │   │
│     → Factor MCP :29010 → 5 tools                    │   │
│     + DB 固定工具 → 2 tools                          │   │
│     = 7 tools (去重后)                               │   │
│                                                      │   │
│  ④ 自适应多轮推理 (≤5 rounds)                        │   │
│     Round 1: LLM → tool_calls (signal + ranking)     │   │
│     Round 2: LLM → tool_calls (zscore + macro + news)│   │
│     Round 3: LLM → final answer                      │   │
│                                                      │   │
│  ⑤ 响应: stream=false→JSON / stream=true→SSE         │   │
└──────────────────────────────────────────────────────┘   │
                                                           │
  DeepSeek API ◄────────────────────────────────────────────┘
```

---

## 四、数据流全景

```
                    ┌─── 数据采集 ───┐
                    │                │
   OpenBB ──► sync_openbb.py ──► macro_indicators (17指标, 71k行)
   freqtrade ──► download-data ──► ohlcv_crypto (10币对, 112k行)
   feedparser ──► sync_news.py ──► news_sentiment (22条)
                    │                │
                    └───────┬────────┘
                            │
                    ┌───────▼────────┐
                    │   dbt 转换      │
                    │   34 models     │
                    │                │
                    │ raw → mart:     │
                    │ 19 technical    │
                    │ +6 macro        │
                    │ =25 factors     │
                    └───────┬────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        mart_hourly_   mart_factor_   mart_factor_
        signals        ic/correlation scoreboard
        (110k rows)    (IC矩阵)       (排名表)
              │             │             │
              └─────────────┼─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │      API Server (:20080)   │
              │  /quant/factors           │
              │  /quant/factor-zscore     │
              │  /quant/ohlcv             │
              │  /quant/chat (AI Agent)   │
              └───────────────────────────┘
```

---

## 五、Skills 系统 (P4 — 对标 Anthropic Fin)

### 目录结构

```
user_data/skills/
├── _anthropic-ref/          📚 Anthropic Fin 参考 (Apache 2.0)
├── factor-deep-dive/        📊 因子深度分析
├── macro-briefing/          📈 每日宏观简报
├── cross-asset-comparison/  🔄 跨资产对比
├── risk-assessment/         ⚠️ 风险评估
└── news-impact/             📰 新闻影响分析
```

### SKILL.md 标准格式 (直接采用 Anthropic 标准)

```yaml
---
name: factor-deep-dive
description: "因子深度分析 — 全面因子归因报告"
version: 1.0.0
metadata:
  portable_runtime: true        # 非 Anthropic 运行时可用
  requires_anthropic_api: false # 任意 LLM Provider 可用
  tags: [crypto, quant, factor]
---

# Skill Name
## Purpose
## Portable Runtime Contract
  ### Inputs        ← 必需输入参数
  ### Outputs       ← 结构化输出格式
## Execution Workflow ← 分步执行指南 (1..N)
## Guardrails         ← 安全边界
## Quality Checklist  ← 输出质量验收 (Checklist)
```

### API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/quant/skills` | GET | 列出可用 Skills |
| `/quant/skills/{name}` | GET | Skill 详情 |
| `/quant/chat` + `skill=` | POST | Skill 驱动对话 |

---

## 六、产品功能矩阵

| 功能模块 | P0-P1 | P2 | P3 | P4 | 说明 |
|---------|:---:|:---:|:---:|:---:|------|
| **数据同步** |||||
| 数字货币行情 | ✅ | | | | Binance 10币对, async |
| 宏观经济 | ✅ | | | | FRED 17指标, async |
| 新闻抓取 | ✅ | | | | RSS 3源 |
| dbt 因子模型 | ✅ | | | | 34 models |
| **因子研究** |||||
| K线图 (Candlestick) | ✅ | | | | + volume |
| 数据源面板 | ✅ | | | | 10币对状态 |
| 因子排名 | ✅ | | | | 实时排名 |
| 因子详情 | ✅ | | | | Z-score + IC |
| **AI 分析** |||||
| 基础对话 | | ✅ | | | 6硬编码工具 |
| MCP 动态工具发现 | | | ✅ | | Factor MCP 5工具 |
| 自适应多轮推理 | | | ✅ | | ≤5 轮 |
| SSE 流式输出 | | | ✅ | | text/event-stream |
| Skills 系统 | | | | ✅ | 5个量化Skills |
| Skill 选择器 (前端) | | | | ✅ | 下拉框 |
| **宏观数据** |||||
| 指标卡片 | ✅ | | | | 17 indicators |
| **经济新闻** |||||
| 新闻列表 + 情感标记 | ✅ | | | | 🟢🔴⚪ |
| **数据同步面板** |||||
| 4源状态 | ✅ | | | | 实时 + 历史日志 |
| **测试** |||||
| 单元测试 | | | | ✅ | 13 tests, 全部通过 |

---

## 七、服务拓扑与端口

```
┌──────────────────────────────────────────────────┐
│                  localhost                        │
│                                                  │
│  :25173  Vue Dashboard (Vite)                    │
│            │                                     │
│            ▼                                     │
│  :20080  Freqtrade API (uvicorn)                 │
│            │                                     │
│     ┌──────┼──────┐                              │
│     ▼      ▼      ▼                              │
│  :29010  :28001  :5433                           │
│  Factor  OpenBB  PostgreSQL                      │
│  MCP     MCP     (Docker)                        │
│                                                  │
│  :23000  Metabase (Docker, 可选)                  │
└──────────────────────────────────────────────────┘

端口规划:
  20000-20999  应用服务
  25000-25999  前端服务
  28000-28999  MCP Servers
  29000-29999  MCP Servers
  5433         PostgreSQL (保持不变)
```

---

## 八、架构演进路线

```
5/9  ████████ P0+P1  数据管道标准化 + 同步修复
     ├─ OpenBB FRED 6→17 indicators
     ├─ Async crypto/news sync
     └─ Bug fixes (query_rows, 唯一索引, 中英文匹配, 数据不刷新)

5/10 ████████ P2+P3  AI Agent v2 → v3
     ├─ P2: 6硬编码工具 + Chat UI
     └─ P3: 动态MCP发现 + 自适应多轮 + SSE流式

5/11 ████████ P4      Skills 系统 ✅
     ├─ 5 Skills (对标 Anthropic Fin 格式)
     ├─ Skill 选择器 (前端)
     ├─ 13 unit tests (全部通过)
     └─ 端口迁移 20000+

──── v4.0 交易闭环 ────

5/12 ░░░░░░░░ Sprint 8  策略生成 + 回测引擎
     ├─ AI 策略生成器 (/trade/strategies)
     ├─ 自动回测 (freqtrade backtesting wrapper)
     ├─ AI 策略排名 + 分析报告
     └─ 前端: 策略实验室 Tab

5/15 ░░░░░░░░ Sprint 9  模拟交易 + 监控
     ├─ 人工审核流程 (批准/修改/拒绝)
     ├─ freqtrade dry-run 管理
     ├─ 交易记录 + K线交易节点
     └─ 前端: 交易台 Tab

5/17 ░░░░░░░░ Sprint 10 报告 + 闭环
     ├─ AI 每日交易报告
     ├─ 净值曲线 + 基准对比
     ├─ AI 改进建议 → 策略迭代
     └─ 前端: 报告 Tab

5/18 ░░░░░░░░ Sprint 11 测试 + 文档
     └─ 单元测试 + 端到端闭环测试
```

---

## 十二、v4.0 交易闭环系统 (⭐新增)

> 详细设计见 `product-design-v4-trading.md`

### 双闭环架构

```
Loop 1 (自动): AI生成策略 → 自动回测 → 排名 → 分析 → 改进 ──┐
                                                              │
Loop 2 (人工): 推荐策略 → 人工批准 → 模拟交易 → 监控 → 日报 ──┤
                                                              │
                                          实盘就绪 ←──────────┘
```

### AI 交易员工角色

- 分析市场 (因子+新闻+宏观) → 生成策略 → 排名 → 推荐
- 不直接执行交易，必须人工批准
- 每日输出交易报告 + 改进建议

### 新增模块

| 模块 | 功能 |
|------|------|
| 策略实验室 | AI 生成+回测+排名 Top 5 |
| 交易台 | 模拟交易 实时监控 交易节点 |
| 交易报告 | 日报/周报 AI分析 改进建议 |
| 数据库 | 5 张新表 (strategies/backtests/trades/reports/approvals) |
| API | 12 个新端点 (/trade/*) |

### 关键指标

| 指标 | 目标 |
|------|------|
| 策略生成频率 | 每日 5 个 |
| 回测覆盖 | 近 7 天 × 10 币对 |
| 模拟资金 | 10,000 USDT |
| 闭环周期 | 1 周 (生成→回测→模拟→改进) |

### 团队评审结论 (2026-05-11)

**四角色评审**: ⚠️ 条件通过 — 方向正确，5 项 Blocking 问题需补齐

| 角色 | 结论 | 核心意见 |
|------|:---:|------|
| 产品经理 | ⚠️ | 缺用户故事+验收标准 |
| 项目经理 | ⚠️ | 排期 8→11 天 |
| 算法工程师 | ⚠️ | 缺过拟合防护+样本外验证 |
| 技术架构师 | ⚠️ | 进程管理+安全需补充 |

**已更新的开发计划**: 详见 `v4-team-review-and-plan.md`
- 总工期: 11.5 天 (含 0.5 天设计补齐)
- 新增: 8 个 User Story + DB schema 修复 + 安全加固 + 算法防护
- 归档: 4 份独立评审报告
```

---

## 九、Anthropic Financial Services Agents 复用分析

### 项目概况
- **发布时间**: 2026-05-10
- **社区 Fork**: `github.com/JKevinXu/financial-services-agent-skills` (Apache 2.0)
- **规模**: 10 Agent + 7 插件 + 11 MCP 连接器

### 复用策略

```
采纳 Anthropic 的 ✅:
  SKILL.md 格式      — 直接套用 YAML frontmatter + References
  Portable Contract  — Input/Output/Guardrails 规范化
  Quality Checklist  — 输出质量验收标准
  Agent Prompt 结构  — references/agent-prompt.md 模式

自研保持的 ⚙️:
  Agent 引擎         — P3 自适应多轮 DeepSeek (优于 Anthropic 便携适配器)
  工具系统           — Factor MCP + DB 工具 (自建数据基础设施)
  数据基础设施       — PG + dbt + freqtrade (核心壁垒)
  前端               — Vue Dashboard (完整产品体验)
```

---

## 十、关键指标

| 指标 | 数值 |
|------|------|
| 宏观指标 | 17 (FRED，含CPI/PCE/失业率/DXY等) |
| 数字货币 | 10 pairs (Binance) |
| 新闻源 | 3 (CoinDesk/CoinTelegraph/Decrypt) |
| 因子数量 | 25 (19 technical + 6 macro) |
| AI 工具数 | 7 (2 DB固定 + 5 MCP动态发现) |
| Skills 数量 | 5 (对标 Anthropic Fin) |
| 推理轮次 | ≤5 自适应 |
| 数据行数 | ohlcv 112k + macro 71k + signals 110k |
| 单元测试 | 13 (全部通过) |
| 服务端口 | 全部 20000+ |

---

## 十一、技术栈

| 层 | 技术 | 说明 |
|-----|------|------|
| 数据采集 | freqtrade + OpenBB 4.7.1 | Binance + FRED/OECD |
| 数据存储 | PostgreSQL 16 (:5433) | Docker, 3 schema |
| 数据转换 | dbt | 34 models, raw → mart |
| 因子引擎 | Python + MCP Server | Factor MCP (:29010) |
| AI Agent | DeepSeek API + FastAPI | Function Calling, ≤5 rounds |
| Skills 系统 | SKILL.md (Anthropic 标准) | YAML frontmatter + References |
| 前端 | Vue 3 + Vite (:25173) | 6 Tab, 热更新 |
| 数据科学 | Metabase (:23000) | 可选 |
| 基础设施 | Docker | PostgreSQL + Metabase |
