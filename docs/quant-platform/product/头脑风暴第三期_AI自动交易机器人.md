# 头脑风暴第三期：AI 自动量化交易机器人

**日期**: 2026-05-11  
**参与角色**: 产品经理 · 算法 · 交易员 · 金融分析师  

---

## 一、核心发现：交易系统已经存在！

### 我们一直在用 freqtrade 做数据下载，但它本身是**完整的交易机器人**

```
已安装并配置好的:
  ✅ freqtrade 2025.3-dev          — 交易引擎
  ✅ FactorSignalStrategy          — 策略（从 PG 读因子信号）
  ✅ config_crypto_mvp.json        — dry_run=True, stake=100 USDT, max=3 trades
  ✅ 因子数据库                     — mart_hourly_signals (110k行, 25因子)
  ✅ backtesting 引擎              — 内置，支持多币对/多时间框架
  ✅ hyperopt 超参优化              — 内置
  ✅ plot profit/dataframe          — 内置可视化

当前只用了:
  freqtrade webserver    — 数据下载 + API
  freqtrade download-data — OHLCV 下载

还没用:
  freqtrade trade --dry-run      — 模拟交易 (纸交易)
  freqtrade backtesting           — 回测
  freqtrade hyperopt              — 策略优化
```

### 现有策略逻辑

```python
class FactorSignalStrategy(IStrategy):
    # Entry: rank_in_date <= 3 AND composite_score > 0.5
    # Exit:  rank_in_date > 5
    # 直接从 quant.mart_hourly_signals 读信号
    # 支持 composite 模式和 single-factor 模式
```

**问题**: 策略只用 `composite_score` 和 `rank_in_date`，没用 AI、没用新闻情绪、没用宏观。

---

## 二、目标架构：AI 驱动的增强策略

```
┌─────────────────────────────────────────────────────────┐
│                   AI 交易策略引擎                         │
│                                                         │
│  输入层                                                  │
│  ├─ mart_hourly_signals  (25 factors, real-time)        │
│  ├─ macro_indicators     (17 indicators)                │
│  ├─ news_sentiment       (sentiment + relevance)        │
│  └─ OHLCV data           (price action)                 │
│                                                         │
│  AI 决策层 (DeepSeek Agent)                             │
│  ├─ 因子综合信号 (现有)                                   │
│  ├─ 宏观环境评估 (新增)                                   │
│  ├─ 新闻情感权重 (新增)                                   │
│  ├─ 技术面确认 (新增)                                     │
│  └─ 动态止损/止盈 (新增)                                  │
│                                                         │
│  输出: buy/sell/hold + position_size + sl/tp            │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│               freqtrade (交易执行层)                       │
│                                                         │
│  Phase 1: dry-run (模拟交易)                              │
│  Phase 2: backtesting (历史回测)                          │
│  Phase 3: live (实盘，可选)                                │
└─────────────────────────────────────────────────────────┘
```

---

## 三、成熟的替代/补充方案对比

| 项目 | 类型 | 优势 | 与我们的关系 |
|------|------|------|------------|
| **freqtrade** ⭐ | 交易引擎 | 完整框架，已安装配置 | **直接使用** |
| **Jesse** | 交易引擎 | 策略 DSL，回测更快 | 可选替代 |
| **Backtrader** | 回测框架 | 通用性强，可转债/期货 | 补充回测 |
| **VectorBT** | 回测框架 | 向量化回测，极速 | 批量回测 |
| **Zipline-Reloaded** | 回测框架 | Pythonic API | 可选 |

**结论: 用 freqtrade 作为交易引擎**。它已经安装、已配置、已有策略、已有数据。其他框架可作为补充回测工具。

---

## 四、实施路线图

### Phase 1: 启动模拟交易 (今天，1小时)

让现有策略在 dry-run 模式下运行起来：

```bash
# 启动模拟交易
freqtrade trade \
  --config user_data/config_crypto_mvp.json \
  --strategy FactorSignalStrategy \
  --dry-run
```

```
产出:
  ✅ 模拟账户 (10,000 USDT 虚拟资金)
  ✅ 自动根据因子排名开仓/平仓
  ✅ 交易日志 + 盈亏记录
  ✅ freqtrade REST API 可查询状态
```

### Phase 2: AI 增强策略 (本周，2天)

```python
class AIFactorSignalStrategy(FactorSignalStrategy):
    """增强版: 因子 + AI分析 + 新闻 + 宏观"""

    def populate_entry_trend(self, df, metadata):
        # 1. 基础因子信号 (原有)
        factor_signal = super().populate_entry_trend(df, metadata)

        # 2. AI 分析确认 (新增)
        ai_analysis = self._get_ai_confirmation(metadata['pair'])
        # AI 返回: {direction: "bullish", confidence: 0.8, reason: "..."}

        # 3. 新闻情绪过滤 (新增)
        news_filter = self._get_news_filter()
        # 负面新闻 > 阈值 → 不开仓

        # 4. 宏观环境过滤 (新增)
        macro_filter = self._get_macro_filter()
        # VIX > 30 或 DXY 强势 → 降低仓位

        # 综合决策
        df['enter_long'] = (
            factor_signal &
            (ai_analysis['confidence'] > 0.6) &
            news_filter &
            macro_filter
        )
        return df
```

### Phase 3: Dashboard 交易面板 (下周，1天)

在 Vue Dashboard 添加第 7 个 Tab "交易监控"：

```
交易监控 Tab:
  ├─ 账户总览 (余额/盈亏/持仓)
  ├─ 当前持仓列表
  ├─ 交易历史 (时间/币对/方向/盈亏)
  ├─ AI 决策日志 (为什么开/平仓)
  └─ 策略参数调整
```

### Phase 4: 回测验证 (下周，1天)

```bash
freqtrade backtesting \
  --config config_crypto_mvp.json \
  --strategy AIFactorSignalStrategy \
  --timerange 20260101-20260510

freqtrade backtesting-analysis  # 查看回测报告
freqtrade plot-profit            # 盈亏曲线
freqtrade plot-dataframe         # 交易信号可视化
```

---

## 五、AI 交易决策接口设计

```python
# POST /quant/trade/signal
{
  "pair": "BTC/USDT",
  "factors": {
    "composite_score": 1.2,
    "rank_in_date": 1,
    "z_mom24": 0.8,
    "z_rsi14": 0.3,
    "z_vix": 1.0,
    "z_dxy": 1.9
  },
  "news_sentiment": "neutral",
  "macro": {"dxy": 97.84, "vix": 17.19}
}

# Response
{
  "action": "buy",           # buy / sell / hold
  "confidence": 0.75,        # 0-1
  "position_ratio": 0.5,     # 建议仓位比例
  "stop_loss": 0.03,         # 止损百分比
  "take_profit": 0.08,       # 止盈百分比
  "reasoning": [
    "因子综合排名#1, 动量强劲",
    "美元走弱利好BTC",
    "新闻中性, 无负面干扰",
    "RSI中性偏低, 有上行空间"
  ]
}
```

---

## 六、关键决策点

| 决策 | 选择 | 原因 |
|------|------|------|
| 交易引擎 | freqtrade | 已安装配置，完整功能 |
| 策略模式 | 增强现有 Strategy | 复用已有因子+AI增强 |
| 回测框架 | freqtrade built-in | 一体集成 |
| 模拟资金 | 10,000 USDT | 标准配置 |
| 最大持仓 | 3 | 控制风险 |
| AI 决策频率 | 每小时 | 与因子更新同步 |

---

## 七、风险评估

| 风险 | 缓解 |
|------|------|
| 因子过拟合 | 用 out-of-sample 回测验证 |
| AI 幻觉 | 决策强制基于数据, AI 只做方向确认 |
| 市场剧烈波动 | 止损 5% + VIX 过滤 |
| API 延迟 | freqtrade 内置缓存机制 |
| 网络断开 | freqtrade 自动重连 + 状态持久化 |
