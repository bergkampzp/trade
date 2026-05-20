# DeepSeek QuantTrader — 架构与产品总结

**日期**: 2026-05-11  
**版本**: v3.0 (P0-P4 完成)

---

## 一、系统全景架构

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
│  │  │ news       │   │ data-sources │   │ _discover_mcp()   │  │  │
│  │  │ macro      │   │ factors      │   │ _load_skill()     │  │  │
│  │  │ crypto     │   │ factor-zscore│   │ _call_llm() ×≤5   │  │  │
│  │  │ dbt        │   │ ohlcv        │   │ SSE streaming     │  │  │
│  │  └────────────┘   └──────────────┘   └───────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
        │                                     │
        ▼                                     ▼
┌───────────────────┐             ┌────────────────────────┐
│   🧠 MCP Servers   │             │   🤖 DeepSeek API      │
│                    │             │   (Function Calling)   │
│  Factor MCP :29010│             └────────────────────────┘
│  ├─ ranking       │
│  ├─ zscore        │
│  ├─ correlation   │
│  ├─ signal        │
│  └─ macro (legacy)│
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

## 二、AI Agent 引擎流程

```
用户提问 ──────────────────────────────────────────────► 最终回答
  │                                                        ▲
  │  "分析BTC风险"                                          │
  ▼                                                        │
┌──────────────────────────────────────────────────────┐   │
│              POST /quant/chat v3                      │   │
│                                                      │   │
│  ① 解析请求                                           │   │
│     skill="risk-assessment"                          │   │
│     pair="BTC/USDT"                                  │   │
│                                                      │   │
│  ② 构建 System Prompt                                │   │
│     ┌──────────────────────────────────┐             │   │
│     │ Base: AI_SYSTEM_PROMPT           │             │   │
│     │ + 当前上下文: BTC/USDT           │             │   │
│     │ + 可用工具: 8 tools listed       │             │   │
│     │ + Skill: risk-assessment SKILL.md│             │   │
│     │   ├─ Purpose                    │             │   │
│     │   ├─ Execution Workflow (6步)   │             │   │
│     │   ├─ Output Format              │             │   │
│     │   └─ Guardrails                 │             │   │
│     └──────────────────────────────────┘             │   │
│                                                      │   │
│  ③ 动态工具发现                                       │   │
│     _discover_mcp_tools() ──► Factor MCP :29010      │   │
│     ├─ get_factor_ranking                            │   │
│     ├─ get_factor_zscore                             │   │
│     ├─ get_factor_correlation                        │   │
│     ├─ get_composite_signal                          │   │
│     └─ get_macro_indicators                          │   │
│     + DB固定工具:                                     │   │
│     ├─ get_crypto_price                              │   │
│     └─ get_news                                      │   │
│     = 7 tools (去重后)                               │   │
│                                                      │   │
│  ④ 自适应多轮推理 (≤5 rounds)                        │   │
│     ┌─────────────────────────────────────┐          │   │
│     │ Round 1: LLM → tool_calls:          │          │   │
│     │   get_composite_signal(BTC)          │          │   │
│     │   get_factor_ranking(5)              │          │   │
│     │                                      │          │   │
│     │ Round 2: LLM → tool_calls:           │          │   │
│     │   get_factor_zscore(BTC, z_rsi14)    │          │   │
│     │   get_macro_indicators()              │          │   │
│     │   get_news(5)                        │          │   │
│     │                                      │          │   │
│     │ Round 3: LLM → final answer          │          │   │
│     │   (数据充足，生成报告)                │          │   │
│     └─────────────────────────────────────┘          │   │
│                                                      │   │
│  ⑤ 响应格式                                           │   │
│     stream=false → JSON {response, tool_calls}       │   │
│     stream=true  → SSE text/event-stream             │   │
└──────────────────────────────────────────────────────┘   │
                                                           │
  DeepSeek API ◄────────────────────────────────────────────┘
```

---

## 三、Skills 系统 (P4 — 对标 Anthropic Fin)

```
user_data/skills/
│
├── factor-deep-dive/          📊 因子深度分析
│   ├── SKILL.md               ← YAML frontmatter + Execution Workflow
│   └── references/
│
├── macro-briefing/            📈 每日宏观简报
│   ├── SKILL.md
│   └── references/
│
├── cross-asset-comparison/    🔄 跨资产对比
│   ├── SKILL.md
│   └── references/
│
├── risk-assessment/           ⚠️ 风险评估
│   ├── SKILL.md
│   └── references/
│
├── news-impact/               📰 新闻影响分析
│   ├── SKILL.md
│   └── references/
│
└── _anthropic-ref/            📚 Anthropic Fin 参考实现 (Apache 2.0)
    └── skills/*/
```

### SKILL.md 标准格式

```yaml
---
name: factor-deep-dive
description: "因子深度分析 — 全面因子归因报告"
version: 1.0.0
metadata:
  portable_runtime: true        # 非 Anthropic 运行时可用
  requires_anthropic_api: false # 任意 LLM 可用
  tags: [crypto, quant, factor]
---

# Skill Name
## Purpose
## Portable Runtime Contract
  ### Inputs        ← 必需输入参数
  ### Outputs       ← 结构化输出格式
## Execution Workflow ← 分步执行指南 (1..N)
## Guardrails         ← 安全边界
## Quality Checklist  ← 输出质量验收
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
              │      API Server           │
              │  /quant/factors           │
              │  /quant/factor-zscore     │
              │  /quant/ohlcv             │
              │  /quant/chat (AI Agent)   │
              └───────────────────────────┘
```

---

## 五、产品功能矩阵

| 功能模块 | P0-P1 | P2 | P3 | P4 | 说明 |
|---------|:---:|:---:|:---:|:---:|------|
| **数据同步** |||||
| 数字货币行情 | ✅ | | | | Binance 10币对, async |
| 宏观经济 | ✅ | | | | FRED 17指标, async |
| 新闻抓取 | ✅ | | | | RSS 3源 |
| dbt 因子模型 | ✅ | | | | 34 models |
| **因子研究** |||||
| K线图 | ✅ | | | | Candlestick + volume |
| 数据源面板 | ✅ | | | | 10币对状态 |
| 因子排名 | ✅ | | | | 实时排名 |
| 因子详情 | ✅ | | | | Z-score + IC |
| **AI 分析** |||||
| 基础对话 | | ✅ | | | 6硬编码工具 |
| MCP动态工具 | | | ✅ | | Factor MCP 5工具 |
| 自适应多轮 | | | ✅ | | ≤5轮推理 |
| SSE流式 | | | ✅ | | text/event-stream |
| Skills系统 | | | | ✅ | 5个量化Skills |
| Skill选择器 | | | | ✅ | 前端下拉框 |
| **宏观数据** |||||
| 指标卡片 | ✅ | | | | 17 indicators |
| **经济新闻** |||||
| 新闻列表 | ✅ | | | | 情感标记 |
| **数据同步面板** |||||
| 4源状态 | ✅ | | | | 实时状态 |
| 执行日志 | ✅ | | | | 历史记录 |
| **DevOps** |||||
| 单元测试 | | | | ✅ | 13 tests |
| 端口标准化 | | | | ✅ | 20000+ |

---

## 六、服务拓扑

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

## 七、开发路线图

```
5/9  ████████ P0+P1  数据管道标准化 + 同步修复
     ├─ OpenBB FRED 6→17 indicators
     ├─ Async crypto/news sync
     └─ Bug fixes (query_rows, 唯一索引, 中英文匹配)

5/10 ████████ P2+P3  AI Agent v2 → v3
     ├─ P2: 6硬编码工具 + Chat UI
     └─ P3: 动态MCP发现 + 自适应多轮 + SSE流式

5/11 ████████ P4      Skills 系统
     ├─ 5 Skills (对标 Anthropic Fin 格式)
     ├─ Skill 选择器
     ├─ 13 unit tests
     └─ 端口迁移 20000+

──── 未来规划 ────

5/13 ░░░░░░░░ P5      多 Agent 模式
     └─ factor-researcher / macro-analyst / risk-assessor

5/15 ░░░░░░░░ P6      MCP 连接器扩展
     └─ OpenBB MCP 正式接入 Chat Agent

5/17 ░░░░░░░░ P7      自动化推送
     └─ Cron 定时简报 + 飞书通知
```

---

## 八、关键指标

| 指标 | 数值 |
|------|------|
| 数据指标 | 17 macro + 10 crypto pairs + RSS |
| 因子数量 | 25 (19 technical + 6 macro) |
| AI 工具数 | 7 (2 DB + 5 MCP 动态发现) |
| Skills 数量 | 5 (对标 Anthropic Fin) |
| 推理轮次 | ≤5 自适应 |
| 单元测试 | 13 (全绿) |
| 服务端口 | 全部 20000+ |
| 代码规模 | ~2500 行 (api_quant.py + 前端 + MCP) |
