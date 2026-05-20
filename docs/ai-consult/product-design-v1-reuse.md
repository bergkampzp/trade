# AI 咨询师平台 — 产品设计与复用方案 v1.0

**版本**: v1.0  
**日期**: 2026-05-18  
**状态**: 产品设计阶段  
**角色**: @产品经理 + @交互设计师  

---

## 一、核心设计原则

```
不重写。只改标签、改数据源、改 prompt。
```

量化交易平台的 8 个 Tab 中，6 个可以直接复用（改内容），0 个需要重新设计交互结构。

| 原则 | 说明 |
|------|------|
| **结构不动** | v-if Tab 切换、AppLayout 双栏布局、vite 配置全部保留 |
| **组件复用** | 每个 Tab 组件保留 80-90% 的 Vue 模板结构，只换 title/数据接口/prompt |
| **Store 复用** | macroStore、syncStore 原样保留；quantStore 改名为 consultStore |
| **API 复用** | REST 认证 (JWT)、同步端点、DB 连接全部保留，只换 SQL 和 LLM prompt |

---

## 二、Tab 复用映射表（8 → 8）

```
┌──────────────────────────────────────────────────────────────┐
│ 量化交易平台（旧）              AI 咨询师平台（新）           │
├──────────────────────────────────────────────────────────────┤
│ ① 因子研究 ──────────────────► ① 企业研究 ★重写             │
│    CandlestickChart               企业K线/估值走势            │
│    DataSourcePanel →              CompanyListPanel            │
│    FactorRankingPanel →           IndustryRankingPanel        │
│    FactorDetailPanel →            CompanyDetailPanel          │
│                                                              │
│ ② 宏观数据 ──────────────────► ② 市场研判 ◇改内容           │
│    MacroDashboard.vue             同样的指标卡片布局           │
│    17 FRED 指标                   增加：A股资金流向/行业PE     │
│                                                              │
│ ③ 经济新闻 ──────────────────► ③ 财经资讯 ◇改数据源         │
│    NewsPanel.vue                  同样的滚动列表 + 情感标记    │
│    RSS (CoinDesk等)               替换：财联社/华尔街见闻      │
│                                                              │
│ ④ AI分析 ───────────────────► ④ AI咨询对话 ◇改prompt       │
│    AIChat.vue                     完全复用，只换 System Prompt │
│    5 Skills(量化)                 替换为 5 咨询 Skills         │
│                                                              │
│ ⑤ 策略实验室 ───────────────► ⑤ 企业分析工作台 ★重写       │
│    TradeLab.vue                   A+B双面：待办列表+分析面板   │
│    (删除)                         企业画像/财务/风险/并购      │
│                                                              │
│ ⑥ 分析结论 ─────────────────► ⑥ 分析报告 ◇改内容            │
│    AnalysisPanel.vue              同样的综合结论布局           │
│    宏观+因子综合                   企业综合评级+投资建议       │
│                                                              │
│ ⑦ 数据同步 ─────────────────► ⑦ 数据同步 ≡不变              │
│    SyncPanel.vue                  新闻/宏观/行情/因子 同步     │
│    完全不变！                     完全不变！                   │
│                                                              │
│ ⑧ 辩论分析 ─────────────────► ⑧ 顾问团辩论 ◇改角色          │
│    DebateLab.vue                  同样的多Agent辩论框架         │
│    5 量化角色(牛/熊/研/交/风)     5 咨询角色(多/空/研/估/法)  │
└──────────────────────────────────────────────────────────────┘

图例： ≡不变  ◇改内容/prompt  ★重写组件
```

---

## 三、详细 Tab 复用设计

### Tab ① 企业研究（替代"因子研究"）

**复用部分**：
- AppLayout 双栏结构（左sidebar + 右main）≡ 不变
- sidebar: DataSourcePanel 的 UI 骨架 → 改为 CompanyListPanel
- sidebar: FactorRankingPanel 的排行列表 UI → 改为 IndustryRankingPanel
- main: CandlestickChart 组件 → 改为 CompanyChart（企业K线+估值走势）
- main: FactorDetailPanel → 改为 CompanyDetailPanel

**改动内容**：

| 旧组件 | 新组件 | 改动量 |
|--------|--------|--------|
| `DataSourcePanel.vue` | `CompanyListPanel.vue` | 替换数据源列表为关注公司列表 |
| `FactorRankingPanel.vue` | `IndustryRankingPanel.vue` | 因子排行 → 行业景气排行 |
| `CandlestickChart.vue` | `CompanyChart.vue` | K线图不变，增加 PE/PB band |
| `FactorDetailPanel.vue` | `CompanyDetailPanel.vue` | 因子Z-score → 财务指标 |

**数据来源变化**：
- 旧：`quant.mart_hourly_signals` (crypto factor signals)
- 新：`consult.company_financials` + `consult.company_kline` (上市公司财务+K线)

---

### Tab ② 市场研判（替代"宏观数据"）

**复用度：90%** — 只改数据源和少量标签

```
MacroDashboard.vue 原样保留：
  ├── 6 指标卡片 Grid 布局        ≡ 不变
  ├── 每个卡片：name / value / change% / freq    ≡ 不变
  ├── BTC 相关性提示              → 改为 "市场情绪仪表"
  └── 数据接口 loadIndicators()   → 指向 consult 数据表
```

**指标替换**：

| 旧指标 | 新指标 |
|--------|--------|
| CPI | CPI |
| Fed Funds Rate | LPR (贷款市场报价利率) |
| VIX | A股波动率指数 |
| DXY (美元指数) | 人民币汇率 |
| 10Y-2Y Spread | 信用利差 |
| Industrial Production | PMI (采购经理指数) |

新增指标：北向资金净流入、两融余额、行业PE中位数

---

### Tab ③ 财经资讯（替代"经济新闻"）

**复用度：85%** — NewsPanel.vue 完全复用，只改数据源

```
NewsPanel.vue 原样保留：
  ├── 新闻列表（标题+来源+情感标记）  ≡ 不变
  ├── 情绪统计（看多/看空/中性）      ≡ 不变
  ├── 自动滚动开关                    ≡ 不变
  └── 数据接口 loadNews()            → 指向 consult_news 表
```

**数据源替换**：

| 旧 RSS 源 | 新 RSS/API 源 |
|-----------|---------------|
| CoinDesk | 财联社 |
| CoinTelegraph | 华尔街见闻 |
| Decrypt | 巨潮资讯（公司公告） |

新闻情感分析保留：关键词库从 crypto 词汇 → 上市公司/行业词汇

---

### Tab ④ AI咨询对话（替代"AI分析"）

**复用度：95%** — AIChat.vue 完全不动代码！

```
AIChat.vue 原样保留：
  ├── 问题建议按钮                    ≡ 不变（改文案）
  ├── Skill 选择器 (下拉)             ≡ 不变（改 Skill 列表）
  ├── 聊天输入框                      ≡ 不变
  ├── 对话历史渲染                    ≡ 不变
  └── SSE 流式输出                    ≡ 不变
```

**改动的只有两个地方**：

1. **System Prompt** — 从量化分析 → 企业咨询
2. **Skills 列表** — 从 5 个量化 Skills → 5 个咨询 Skills

| 旧 Skill | 新 Skill |
|----------|----------|
| 因子深度分析 | 企业深度分析 |
| 每日宏观简报 | 每日市场简报 |
| 跨资产对比 | 同业对比分析 |
| 风险评估 | 企业风险评估 |
| 新闻影响分析 | 政策影响分析 |

MCP 工具 → 替换为 consult MCP（企业数据查询 + 知识库检索）

---

### Tab ⑤ 企业分析工作台（替代"策略实验室"）

**这是唯一需要较大改动的 Tab** — 采用 A+B 双面设计

```
A面 (左侧) — 待办驱动
┌──────────────────────────┐
│ 📋 分析待办               │
│ ┌──────────────────────┐ │
│ │ 迈信林(688685)  ③天  │ │  ← 按状态/等待时间排序
│ │ 安诺奇           ⑤天  │ │
│ │ 待添加...             │ │
│ └──────────────────────┘ │
│ [+ 添加关注公司]         │
└──────────────────────────┘

B面 (右侧) — 企业分析面板
┌──────────────────────────┐
│ 迈信林 (688685)  进度●●○○ │
│ ┌────┬────┬────┬────┐   │
│ │画像│财务│风险│并购│   │  ← 4 个分析维度
│ └────┴────┴────┴────┘   │
│                         │
│ ┌──────────────────────┐ │
│ │ [当前选中的分析面板]   │ │  ← 动态切换
│ └──────────────────────┘ │
│                         │
│ [生成报告] [咨询建议]     │
└──────────────────────────┘
```

**4 个分析维度面板**（全部复用现有组件的卡片/表格样式）：

| 面板 | 复用来源 | 内容 |
|------|----------|------|
| 企业画像 | FactorDetailPanel 布局 | 基本信息、主营业务、管理层、股权结构 |
| 财务分析 | 回测指标表 布局 | 营收/利润/现金流/负债率 趋势图 |
| 风险评估 | 同步面板 状态卡片 | 财务风险/行业风险/政策风险 评分 |
| 并购咨询 | AI 分析 流式输出 | RAG 检索 → 相似案例 → 方案建议 |

---

### Tab ⑥ 分析报告（替代"分析结论"）

**复用度：100%** — AnalysisPanel.vue 只改标题和内容字段

```
AnalysisPanel.vue 原样保留：
  ├── 综合信号摘要               → 综合评级
  ├── 多维度评分卡片             → 企业健康度评分
  └── 详细分析列表               → 分析结论列表
```

---

### Tab ⑦ 数据同步

**复用度：100%** — **完全不动任何代码**

同步面板的 4 个数据源：新闻/宏观/行情/因子 → 全部保留！因为：
- 新闻同步：从 crypto RSS → 财经 RSS（改 sync_news 脚本）
- 宏观同步：FRED → FRED + A股宏观（改 sync_macro 脚本）
- 行情同步：crypto → A股（改数据源）
- dbt 模型：19 因子 → 企业评估因子（改 dbt models）

前端 SyncPanel.vue **完全不动**。

---

### Tab ⑧ 顾问团辩论（替代"辩论分析"）

**复用度：85%** — DebateLab.vue 复用

```
DebateLab.vue 保留：
  ├── 股票选择 (4 个按钮)          → 改为关注公司选择
  ├── K线图 + 行情数据              → 企业K线 + 财务摘要
  ├── 辩论轮次选择                  ≡ 不变
  ├── [开始] 按钮                   ≡ 不变
  └── process_log 时间线可视化      ≡ 不变
```

**5 Agent 角色替换**：

| 旧角色 (量化) | 新角色 (咨询) |
|---------------|---------------|
| 📈 看涨分析师 | 📈 多头分析师（企业价值看多原因） |
| 📉 看跌分析师 | 📉 空头分析师（企业风险/看空原因） |
| 🔬 研究经理 | 🔬 行业研究员（行业对比/竞争格局） |
| 💹 交易员 | 💹 估值分析师（PE/PB/DCF估值） |
| 🛡️ 风险官 | 🛡️ 合规风控官（政策/法律/治理风险） |

角色 System Prompt 从量化分析 → 企业分析

---

## 四、复用统计

```
总代码复用率：约 75%

┌─────────────────┬──────────┐
│ 组件层           │ 复用度    │
├─────────────────┼──────────┤
│ App.vue         │ 95% 只改tabs数组│
│ AppLayout.vue   │ 100%        │
│ SyncPanel.vue   │ 100%        │
│ AIChat.vue      │ 95%         │
│ DebateLab.vue   │ 85%         │
│ MacroDashboard  │ 90%         │
│ NewsPanel       │ 85%         │
│ AnalysisPanel   │ 100%        │
│ 企业研究(新)     │ 70% 复用子组件│
│ 分析工作台(新)   │ 50% 新设计    │
├─────────────────┼──────────┤
│ Store 层         │           │
│ syncStore       │ 100%        │
│ macroStore      │ 90%         │
│ quantStore→consultStore│ 80% │
│ tradeStore→workStore │ 50%   │
│ debateStore     │ 80%         │
├─────────────────┼──────────┤
│ API 层           │           │
│ client.ts       │ 100% (JWT) │
│ sync.ts         │ 100%        │
│ quant.ts→consult.ts│ 80%     │
│ trade.ts→work.ts│ 50%         │
│ debate.ts       │ 80%         │
└─────────────────┴──────────┘
```

---

## 五、交互设计规范

### 5.1 全局交互保持

- Tab 切换：v-if 模式，`switchTab()` 主动刷新（完全不动）
- JWT 认证：quant/quant123（或改为 consult/consult123）
- 同步按钮：右上角 ⟳ 同步（完全不动）
- 顶栏：Tab 导航 + 同步按钮（完全不动）
- 左侧栏/右侧主区域：AppLayout 双栏（不变）

### 5.2 Tab 视觉标签替换

```
旧 Tab 标签               新 Tab 标签
──────────────────────    ──────────────────────
① 因子研究                 ① 企业研究
② 宏观数据                 ② 市场研判
③ 经济新闻                 ③ 财经资讯
④ AI分析                   ④ AI咨询对话
⑤ 策略实验室               ⑤ 企业分析工作台
⑥ 分析结论                 ⑥ 分析报告
⑦ 数据同步                 ⑦ 数据同步       ← 不变
⑧ 辩论分析                 ⑧ 顾问团辩论
```

### 5.3 配色保持

保留现有深色主题配色（bg: #0A0E1A, primary: #F59E0B, accent: #3B82F6），
只将部分 `green` 色调从 crypto 绿 → 金融蓝，强调专业咨询感。

---

## 六、实施计划

### Phase 1: 框架搭建（1 天）
1. Git worktree: `ai-consult` 基于 gitee/ai-consult 分支
2. App.vue tabs 数组改名
3. 所有 Tab 标签文案替换
4. 验证 8 个 Tab 正常显示（空状态占位）

### Phase 2: 低改动 Tab（1 天）
5. AI咨询对话：System Prompt + 5 Skills 替换
6. 财经资讯：RSS 数据源替换
7. 市场研判：FRED 指标 → 中国市场指标
8. 数据同步：验证现有同步对 A 股数据可用

### Phase 3: 中改动 Tab（1.5 天）
9. 企业研究：替换子组件（CompanyListPanel / IndustryRanking / CompanyChart / CompanyDetail）
10. 分析报告：字段替换 + 结论模板
11. 顾问团辩论：Agent 角色 + System Prompt 替换

### Phase 4: 新设计 Tab（2 天）
12. 企业分析工作台：A+B 双面设计 + 4 分析维度面板

### 总计：~5.5 天
