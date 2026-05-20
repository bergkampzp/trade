-- Sprint 2 Metabase Dashboard: 因子研究闭环
-- Create these as "Native query" cards in Metabase, then add to a dashboard.
-- Database: 电力数仓 (id=2, dest-postgres, warehouse DB)

-- ============================================================
-- Card 1: Factor Scoreboard (latest run)
-- ============================================================
SELECT
    factor_name,
    verdict,
    ROUND(ic_mean::numeric, 4) AS ic_mean,
    ROUND(ic_ir::numeric, 3) AS ic_ir,
    ROUND(quantile_sharpe::numeric, 2) AS quantile_sharpe,
    ROUND(max_corr_with_accepted::numeric, 3) AS max_corr,
    ROUND(backtest_sharpe::numeric, 3) AS bt_sharpe,
    ROUND(backtest_max_dd::numeric * 100, 2) AS bt_max_dd_pct,
    updated_at
FROM quant.mart_factor_scoreboard
WHERE run_date = (SELECT MAX(run_date) FROM quant.mart_factor_scoreboard)
ORDER BY
    CASE verdict
        WHEN 'PASS' THEN 0
        WHEN 'FAIL_TIER3_DD' THEN 1
        WHEN 'FAIL_TIER3_SHARPE' THEN 2
        WHEN 'FAIL_TIER2_CORR' THEN 3
        WHEN 'FAIL_TIER2_SHARPE' THEN 4
        WHEN 'FAIL_TIER1' THEN 5
        ELSE 9
    END,
    ABS(ic_mean) DESC NULLS LAST;


-- ============================================================
-- Card 2: IC Heatmap (factor × month)
-- ============================================================
SELECT
    factor_name,
    TO_CHAR(month, 'YYYY-MM') AS month,
    ROUND(monthly_ic::numeric, 4) AS monthly_ic,
    ROUND(rolling_3m_ic::numeric, 4) AS rolling_3m_ic
FROM quant.mart_factor_ic_rolling
ORDER BY factor_name, month;


-- ============================================================
-- Card 3: Correlation Matrix
-- ============================================================
SELECT
    factor_a,
    factor_b,
    ROUND(corr_pearson::numeric, 3) AS corr
FROM quant.mart_factor_correlation
UNION ALL
SELECT
    factor_b AS factor_a,
    factor_a AS factor_b,
    ROUND(corr_pearson::numeric, 3) AS corr
FROM quant.mart_factor_correlation
WHERE factor_a <> factor_b
ORDER BY factor_a, factor_b;


-- ============================================================
-- Card 4: Tier Progression Funnel
-- ============================================================
SELECT
    'All Candidates' AS stage, COUNT(*) AS n, 0 AS stage_order
FROM quant.mart_factor_scoreboard WHERE run_date = (SELECT MAX(run_date) FROM quant.mart_factor_scoreboard)
UNION ALL
SELECT
    'Tier 1 Pass (IC)' AS stage, SUM(tier1_pass::int) AS n, 1
FROM quant.mart_factor_scoreboard WHERE run_date = (SELECT MAX(run_date) FROM quant.mart_factor_scoreboard)
UNION ALL
SELECT
    'Tier 2 Pass (Quantile+Corr)' AS stage, SUM(tier2_pass::int) AS n, 2
FROM quant.mart_factor_scoreboard WHERE run_date = (SELECT MAX(run_date) FROM quant.mart_factor_scoreboard)
UNION ALL
SELECT
    'Tier 3 Pass (Backtest)' AS stage, SUM(tier3_pass::int) AS n, 3
FROM quant.mart_factor_scoreboard WHERE run_date = (SELECT MAX(run_date) FROM quant.mart_factor_scoreboard)
ORDER BY stage_order;


-- ============================================================
-- Card 5: Top Factor NAV Curves (from Tier 3 runs)
-- ============================================================
SELECT
    run_id,
    date,
    nav
FROM quant.mart_backtest_nav
WHERE run_id LIKE 'sprint2_%'
ORDER BY run_id, date;


-- ============================================================
-- Card 6: IC Stability (rolling 3M IC per factor)
-- ============================================================
SELECT
    factor_name,
    month,
    rolling_3m_ic
FROM quant.mart_factor_ic_rolling
WHERE rolling_3m_ic IS NOT NULL
ORDER BY factor_name, month;
