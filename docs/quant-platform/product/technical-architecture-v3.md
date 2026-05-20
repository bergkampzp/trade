# DeepSeek QuantTrader — 技术架构 v3.0

**更新日期**: 2026-05-10  
**状态**: P0-P3 完成  

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    Vue 3 Dashboard (:5173)               │
│  ┌──────┬──────┬──────┬──────┬──────┬──────┐           │
│  │因子研究│宏观数据│经济新闻│AI分析│分析结论│数据同步│           │
│  └──────┴──────┴──────┴──────┴──────┴──────┘           │
├─────────────────────────────────────────────────────────┤
│              Freqtrade API Server (:8080)                │
│  ┌────────────────────────────────────────────────┐     │
│  │  api_quant.py                                   │     │
│  │  ├─ /quant/data-sources    → PostgreSQL         │     │
│  │  ├─ /quant/factors         → dbt models         │     │
│  │  ├─ /quant/sync/*          → 数据同步            │     │
│  │  ├─ /quant/chat            → AI Agent v3        │     │
│  │  └─ /quant/skills          → Skills System (P4)│     │
│  └────────────────────────────────────────────────┘     │
├─────────────────────────────────────────────────────────┤
│                    MCP Servers                           │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │ Factor MCP :9010 │  │ OpenBB MCP :8001 │            │
│  │  5 quant tools   │  │ economy + crypto │            │
│  └──────────────────┘  └──────────────────┘            │
├─────────────────────────────────────────────────────────┤
│                    Data Layer                            │
│  ┌────────────────────────────────────────────────┐     │
│  │  PostgreSQL :5433 (warehouse)                   │     │
│  │  ├─ quant_raw.ohlcv_crypto      (112k rows)    │     │
│  │  ├─ quant_raw.macro_indicators  (71k rows)     │     │
│  │  ├─ quant_raw.news_sentiment    (22 rows)      │     │
│  │  ├─ quant.mart_hourly_signals   (110k rows)    │     │
│  │  └─ quant_raw.sync_status       (4 sources)    │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ freqtrade    │  │ OpenBB 4.7.1 │  │ feedparser   │  │
│  │ Binance      │  │ FRED (17指标) │  │ RSS (3源)    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 二、AI Agent 引擎 (P3 — 当前)

```
POST /quant/chat
  ↓
api_quant_chat_v2()
  ├─ _discover_mcp_tools()          ← Factor MCP :9010/tools
  │   └─ 5 tools: get_factor_ranking, get_factor_zscore,
  │                get_factor_correlation, get_composite_signal,
  │                get_macro_indicators
  ├─ _DB_TOOLS                      ← 3 fixed DB tools
  │   └─ get_crypto_price, get_news, get_macro_indicators
  ├─ _call_llm()                    ← DeepSeek API
  │   └─ Adaptive multi-turn (≤5 rounds)
  └─ Response
      ├─ stream=false → JSON {response, tool_calls}
      └─ stream=true  → SSE text/event-stream
```

## 三、Skills 系统 (P4 — 规划中)

### 架构

```
user_data/skills/
├── _anthropic-ref/          ← Anthropic Fin 参考 (Apache 2.0)
├── factor-deep-dive/        ← P4-1
│   ├── SKILL.md
│   └── references/
├── macro-briefing/          ← P4-2
├── cross-asset-comparison/  ← P4-3
├── risk-assessment/         ← P4-4
└── news-impact/             ← P4-5

POST /quant/chat?skill=factor-deep-dive
  → 加载 SKILL.md → 注入 system prompt
  → 加载 references/ → 上下文增强
  → 按 Execution Workflow 分步执行
  → 输出结构化报告
```

### Skill 加载流程

```
1. 解析 SKILL.md YAML frontmatter
2. 读取 agent-prompt.md 作为系统提示词
3. 根据 skill 类型注入专属工具集
4. 按 Portable Runtime Contract 验证输入/输出
5. 执行 Quality Checklist
```

## 四、多 Agent 模式 (P5)

```
                    ┌──────────────────┐
                    │   Agent Factory   │
                    └────────┬─────────┘
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│factor-researcher│ │ macro-analyst   │ │ risk-assessor   │
│  因子研究员      │ │  宏观分析师      │ │  风险评估师      │
├─────────────────┤ ├─────────────────┤ ├─────────────────┤
│Skills:          │ │Skills:          │ │Skills:          │
│ factor-deep-    │ │ macro-briefing  │ │ risk-assessment │
│ dive            │ │ cross-asset     │ │ news-impact     │
├─────────────────┤ ├─────────────────┤ ├─────────────────┤
│Tools:           │ │Tools:           │ │Tools:           │
│ ranking, zscore │ │ macro, news     │ │ signal, zscore  │
│ correlation     │ │ crypto_price    │ │ correlation     │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 五、数据流

```
                    Sync Pipeline
                    ════════════
                    
  OpenBB FRED ──→ sync_openbb.py ──→ macro_indicators (17)
  freqtrade    ──→ download-data  ──→ ohlcv_crypto (10 pairs)
  feedparser   ──→ sync_news.py   ──→ news_sentiment
  
                    dbt Pipeline
                    ════════════
                    
  ohlcv_crypto ──┐
  macro_indicators├──→ dbt run ──→ mart_hourly_signals (25 factors)
  news_sentiment ─┘                ├─ mart_factor_values_long
                                   ├─ mart_factor_ic
                                   ├─ mart_factor_correlation
                                   └─ mart_factor_scoreboard
```

---

## 六、API 端点清单

| 端点 | 方法 | 功能 | 状态 |
|------|------|------|------|
| `/quant/data-sources` | GET | 数据源/币对列表 | ✅ |
| `/quant/factors` | GET | 因子列表 | ✅ |
| `/quant/factors/{name}` | GET | 因子详情 | ✅ |
| `/quant/factor-zscore` | GET | 因子 Z-score | ✅ |
| `/quant/factor-correlation` | GET | 因子相关性 | ✅ |
| `/quant/ohlcv` | GET | OHLCV 数据 | ✅ |
| `/quant/sync/status` | GET | 同步状态 | ✅ |
| `/quant/sync/logs` | GET | 同步日志 | ✅ |
| `/quant/sync/news` | POST | 触发新闻同步 | ✅ Async |
| `/quant/sync/macro` | POST | 触发宏观同步 | ✅ Async |
| `/quant/sync/crypto` | POST | 触发行情同步 | ✅ Async |
| `/quant/sync/dbt` | POST | 触发 dbt | ✅ |
| `/quant/chat` | POST | AI 分析对话 | ✅ v3 |
| `/quant/chat?skill=` | POST | Skills 驱动对话 | 🔜 P4 |
| `/quant/skills` | GET | 可用 Skills 列表 | 🔜 P4 |
| `/quant/skills/{name}` | GET | Skill 详情 | 🔜 P4 |
| `/quant/chat?agent=` | POST | 多 Agent 模式 | 🔜 P5 |

---

## 七、服务清单

| 服务 | 端口 | 进程 | 状态 |
|------|------|------|------|
| Freqtrade API | 8080 | `python -m freqtrade webserver` | ✅ |
| Vue Dashboard | 5173 | `vite` | ✅ |
| PostgreSQL | 5433 | Docker `warehouse` | ✅ |
| Factor MCP | 9010 | `factor_mcp_server.py --http` | ✅ |
| OpenBB MCP | 8001 | `openbb-mcp --categories economy,crypto` | ✅ |
| Metabase | 3000 | Docker | ✅ |

---

## 八、关键技术决策

| 决策 | 选型 | 原因 |
|------|------|------|
| LLM Provider | DeepSeek API | 国内可用 + 性价比 |
| Agent 框架 | 自研 (FastAPI) | 避免 pydantic-ai 依赖，灵活可控 |
| Skill 格式 | Anthropic SKILL.md 标准 | 社区标准，直接兼容 |
| MCP 协议 | HTTP REST (非 stdio) | 简化部署，支持多客户端 |
| 数据存储 | PG + dbt | SQL 标准化，可复现 |
| 前端 | Vue 3 + Vite | 轻量，热更新 |
| 网络方案 | VPN (按需) | 中国内地访问 Binance/RSS |
