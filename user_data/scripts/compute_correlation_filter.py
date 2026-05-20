"""Tier 2 correlation filter: max |corr| of each candidate with accepted factors."""

from __future__ import annotations

import psycopg2


CORR_SQL = """
WITH accepted AS (
    SELECT factor_name FROM quant.dim_accepted_factors
),
-- mart_factor_correlation stores upper triangle only (a <= b)
-- Expand to both directions for lookup
full_corr AS (
    SELECT factor_a, factor_b, corr_pearson FROM quant.mart_factor_correlation
    UNION ALL
    SELECT factor_b, factor_a, corr_pearson FROM quant.mart_factor_correlation
    WHERE factor_a <> factor_b
)
SELECT
    c.factor_a AS candidate,
    MAX(ABS(c.corr_pearson)) AS max_corr_accepted
FROM full_corr c
JOIN accepted a ON c.factor_b = a.factor_name
WHERE c.factor_a <> c.factor_b
  AND c.factor_a NOT IN (SELECT factor_name FROM accepted)
GROUP BY c.factor_a
"""


def get_max_corr_with_accepted(dsn: str) -> dict[str, float]:
    """Return {factor_name: max_abs_corr_with_accepted}."""
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(CORR_SQL)
            return {row[0]: float(row[1]) for row in cur.fetchall()}
