# Sprint 2: 因子研究闭环 — 运行手册

## 概述

研究闭环对候选因子跑 3 级评估漏斗，自动输出 PASS/FAIL 判定：

```
14 个因子 → Tier 1 (IC) → Tier 2 (分位数+相关性) → Tier 3 (freqtrade 全回测) → Scoreboard
```

## 快速开始

```bash
cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp

# 全量评估所有因子（含 dbt 刷新 + 回测，~5 分钟）
python user_data/scripts/run_research_loop.py --factors all

# 只跑 Tier 1+2（跳过回测，~10 秒）
python user_data/scripts/run_research_loop.py --factors all --skip-tier3

# 跳过 dbt 刷新（数据已是最新）
python user_data/scripts/run_research_loop.py --factors all --skip-dbt

# 只评估指定因子
python user_data/scripts/run_research_loop.py --factors rsi_14,mfi_14

# 查看计划但不执行
python user_data/scripts/run_research_loop.py --dry-run
```

## 如何添加新因子

### 3 步清单

1. **创建 dbt 模型**：在 `/home/zp/airbyte/quant_warehouse/models/features/` 下创建 `feat_<name>.sql`
   - 输入：`{{ ref('stg_ohlcv_crypto') }}` 或 `{{ ref('int_hourly_returns') }}`
   - 输出列：`pair, date, <name>`
   - 参考现有模型如 `feat_momentum_24h.sql`

2. **注册因子**：在 `user_data/factors.yml` 中添加条目
   ```yaml
   - name: my_new_factor
     bucket: A  # A=股票经典, C=微结构, B=链上(Sprint 3)
     feature_model: feat_my_new_factor
     raw_column: my_new_factor
     zscore_column: z_my_new
     direction: positive  # positive=越高越看多, negative=反之
     description: "描述"
   ```

3. **更新 mart**：在 `models/mart/mart_hourly_signals.sql` 中
   - 添加 `LEFT JOIN {{ ref('feat_my_new_factor') }} alias USING (pair, date)`
   - 在 `scored` CTE 中添加 z-score 计算
   - 在 `SELECT` 中暴露 `z_my_new` 列
   - 在 `models/mart/mart_factor_values_long.sql` 中添加 `UNION ALL` 块

然后运行 `python run_research_loop.py --factors my_new_factor` 即可评估。

## 评估阈值

| Tier | 指标 | 阈值 | 说明 |
|------|------|------|------|
| T1 | \|IC mean\| | ≥ 0.005 | 加密 1h 频率 IC 普遍较低 |
| T1 | \|IC IR\| | ≥ 0.3 | IC 信息比率 |
| T2 | 分位数 Sharpe | ≥ 0.8 | 年化 (×√(24×365)) |
| T2 | max \|corr\| with accepted | ≤ 0.7 | 与已接受因子的相关性 |
| T3 | 回测 Sharpe | ≥ 1.0 | freqtrade 全回测 |
| T3 | 最大回撤 | ≤ 15% | 账户级别 |

阈值在 `run_research_loop.py` 顶部定义，可按需调整。

## 如何"祝福"一个因子（加入已接受集）

当一个因子通过所有 3 级评估后：

```sql
INSERT INTO quant.dim_accepted_factors (factor_name, notes)
VALUES ('my_new_factor', 'Sprint 2 首批通过');
```

此后新因子的 Tier 2 相关性检查会自动包含该因子。

## 输出物

- **PG 表**：`quant.mart_factor_scoreboard` — 每次运行的完整评分板
- **Markdown 报告**：`/tmp/sprint2_report_<date>.md`
- **回测 NAV 曲线**：`quant.mart_backtest_nav`，`run_id` 前缀 `sprint2_`
- **Metabase 面板**："因子研究闭环"，SQL 在 `docs/sprint2_dashboard_queries.sql`

## 数据覆盖

- BTC/USDT: 3 年 (2023-04 → 2026-04), 26284 行
- 其他 9 个 pair: 1 年 (2025-04 → 2026-04), 各 8763 行
- 所有数据为 1h K 线
- dbt features 层产出 87k-105k 行/因子

## 故障排查

- **dbt 报错**：检查 PG 是否运行 (`psql "host=localhost port=5433 ..."`)
- **Tier 3 回测失败**：查看 `/tmp/sprint2_runs/<factor>.log`
- **所有因子被 Tier 1 淘汰**：阈值可能太严，调低 `TIER1_IC_MEAN`
- **相关性过高**：`reversal_24h` 和 `momentum_24h` 相关性=1.0 是正确的（互为取反）
