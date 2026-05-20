# DeepSeek QuantTrader — 开发计划 v3.0

**制定日期**: 2026-05-10  
**当前版本**: P3 完成  
**下一里程碑**: P4 Skills 系统  

---

## Sprint 1: 基础设施与数据管道 ✅ 已完成 (5/9)

| 任务 | 状态 | 产出 |
|------|:---:|------|
| PostgreSQL + dbt 环境搭建 | ✅ | warehouse DB, 33 models |
| freqtrade Binance 数据下载 | ✅ | 10 pairs OHLCV |
| RSS 新闻抓取 | ✅ | 22 articles |
| OpenBB FRED 宏观经济同步 | ✅ | 6 indicators → 17 indicators |
| 前端 Dashboard 基础框架 | ✅ | Vue 3 + 6 tabs |

## Sprint 2: 同步系统修复 ✅ 已完成 (5/10)

| 任务 | 状态 | Bug 修复 |
|------|:---:|------|
| `quant_db.py` UPDATE 崩溃 | ✅ | `cur.description is None` 检查 |
| 新闻唯一索引缺失 | ✅ | `CREATE UNIQUE INDEX` |
| Crypto 同步阻塞前端 | ✅ | threading 异步 |
| 中英文匹配断裂 | ✅ | `id` 字段 + status 保留英文 |
| 因子页数据不刷新 | ✅ | `refreshCurrentData()` |

## Sprint 3: AI 对话系统 ✅ 已完成 (5/10)

| 迭代 | 任务 | 状态 |
|------|------|:---:|
| P2 | 硬编码 6 工具 + 固定 2 轮 LLM 调用 | ✅ |
| P2 | Chat API + 前端 AIChat.vue | ✅ |
| P3 | 动态 MCP 工具发现 (Factor MCP 5 tools) | ✅ |
| P3 | 自适应多轮推理 (≤5 rounds) | ✅ |
| P3 | SSE 流式输出 | ✅ |
| P3 | 工具去重 + json/os/requests 模块导入修复 | ✅ |

## Sprint 4: Skills 系统 🔜 本周 (5/11-5/12)

**对标**: Anthropic Financial Services Agents SKILL.md 格式  
**目标**: 5 个量化分析 Skills，前端可调用  

### 4.1 基础设施 (半天)

| # | 任务 | 文件 |
|---|------|------|
| 4.1.1 | 创建 `user_data/skills/` 目录结构 | 目录 |
| 4.1.2 | 实现 `_load_skill(name)` 函数 | `api_quant.py` |
| 4.1.3 | 实现 Skill YAML 解析器 | `api_quant.py` |
| 4.1.4 | API: `GET /quant/skills` | `api_quant.py` |
| 4.1.5 | API: `POST /quant/chat?skill=factor-deep-dive` | `api_quant.py` |

### 4.2 Skill 1: factor-deep-dive (半天)

| # | 任务 |
|---|------|
| 4.2.1 | 创建 `skills/factor-deep-dive/SKILL.md` |
| 4.2.2 | 创建 `references/factor-whitelist.md` |
| 4.2.3 | 编写 agent-prompt.md (因子研究员角色) |
| 4.2.4 | 测试: "分析 BTC 的动量因子" |

### 4.3 Skill 2-5 (1 天)

| # | Skill | 功能 |
|---|-------|------|
| 4.3.1 | `macro-briefing` | 生成每日宏观简报 |
| 4.3.2 | `cross-asset-comparison` | 多币对横向对比 |
| 4.3.3 | `risk-assessment` | 风险评估与归因 |
| 4.3.4 | `news-impact` | 新闻事件影响分析 |

### 4.4 前端适配 (半天)

| # | 任务 |
|---|------|
| 4.4.1 | AIChat.vue 添加 Skill 选择下拉框 |
| 4.4.2 | Skill 详情面板 (显示描述+输入参数) |
| 4.4.3 | Skills 列表 API 集成 |

---

## Sprint 5: 多 Agent 模式 🔜 下周 (5/13-5/14)

| # | 任务 | 说明 |
|---|------|------|
| 5.1 | Agent 工厂模式 | `AGENTS` 注册表 |
| 5.2 | `POST /quant/chat?agent=factor-researcher` | 按 Agent 加载专属 Skills + Tools |
| 5.3 | `macro-analyst` Agent | 绑定 macro-briefing + cross-asset |
| 5.4 | `risk-assessor` Agent | 绑定 risk-assessment + news-impact |
| 5.5 | 前端 Agent 选择器 | AIChat.vue 顶部 Agent 切换 |

---

## Sprint 6: MCP 连接器扩展 🔜 (5/15-5/16)

| # | 任务 | 说明 |
|---|------|------|
| 6.1 | OpenBB MCP 工具接入 Chat Agent | `_discover_mcp_tools()` 增加 OpenBB MCP |
| 6.2 | MCP Server 注册标准化 | `MCP_SERVERS` 配置列表 |
| 6.3 | 测试 OpenBB 经济数据工具 | obb.economy.cpi, gdp, unemployment |
| 6.4 | 健康检查端点 | `GET /quant/mcp/status` |

---

## Sprint 7: 自动化与推送 🔜 (5/17-5/18)

| # | 任务 | 说明 |
|---|------|------|
| 7.1 | 定时宏观简报 (cron) | 每日 08:00 自动生成并推送 |
| 7.2 | 因子异常检测告警 | 3σ 异常 → 飞书推送 |
| 7.3 | 新闻情感日报 | 每日新闻汇总 + 情感统计 |
| 7.4 | Cron 管理端点 | `POST /quant/cron/*` |

---

## 技术债务与优化

| # | 任务 | 优先级 |
|---|------|:---:|
| T1 | 统一错误处理中间件 | P1 |
| T2 | API 响应日志 | P1 |
| T3 | 数据库连接池监控 | P2 |
| T4 | 前端 loading/error 状态完善 | P2 |
| T5 | Docker Compose 一键启动 | P2 |
| T6 | 单元测试覆盖 | P3 |
| T7 | API 文档补充 (OpenAPI tags) | P3 |

---

## 里程碑时间线

```
5/9  ████████ P0+P1 数据管道标准化
5/10 ████████ P2 AI 对话 + P3 动态MCP + 同步修复
     ├─ bug fixes: query_rows, 新闻索引, 中英文匹配, 同步阻塞
     └─ P3: 8 tools (3 DB + 5 MCP), adaptive multi-turn, SSE streaming
5/11 ████████ P4 Skills 系统
     ├─ 5 Skills + 基础设施
     └─ 前端适配
5/12 ░░░░░░░░ P4 收尾 + 测试
5/13 ████████ P5 多 Agent 模式
5/14 ░░░░░░░░ P5 收尾
5/15 ████████ P6 MCP 扩展
5/16 ░░░░░░░░ P6 收尾
5/17 ████████ P7 自动化推送
5/18 ░░░░░░░░ 收尾 + 技术债务
```

---

## 当前状态摘要

```
已完成:
  ✅ 数据引擎: 17 macro + 10 crypto pairs + RSS news
  ✅ 因子引擎: 25 factors via dbt (19 technical + 6 macro)
  ✅ AI Agent: v3 adaptive multi-turn + dynamic MCP
  ✅ Dashboard: 6 tabs (因子/宏观/新闻/AI/分析/同步)
  ✅ Sync: 4 sources all async

进行中:
  🔜 P4 Skills 系统 (对标 Anthropic Fin)

数据规模:
  ohlcv_crypto:           112,430 rows (10 pairs)
  macro_indicators:        71,100 rows (17 indicators)
  news_sentiment:              22 articles
  mart_hourly_signals:    110,000 rows (25 factors)
```
