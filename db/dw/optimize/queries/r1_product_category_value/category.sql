-- R1 Product & Category Value — level: category (top of Category > Product)
-- Which categories carry the most delivered units and list-price value?
-- OLAP: roll-up to a grand total (ROLLUP); slice by period; dice by vehicle,
-- order-size group and category.
--
-- Parameters (empty string = all):
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   month       '1'..'12'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   size_group  'Light' | 'Heavy'
--
-- Columns: category, units, value, value_share_pct, value_rank, is_total
--   One row per category plus an 'All categories' grand total (is_total).
--   value = list-price value (quantity x current list price), not revenue.

-- OPTIMIZED (Strategy C): reads AGG_CATEGORY_PERIOD instead of FACT_ORDERITEM + 4 dimension joins; same columns and types.
WITH filtered AS (
  SELECT a."category", a."units", a."value"
  FROM "AGG_CATEGORY_PERIOD" a
  WHERE (:'year'       = '' OR a."year"        = nullif(:'year', '')::int)
    AND (:'quarter'    = '' OR a."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'      = '' OR a."monthNumber" = nullif(:'month', '')::int)
    AND (:'vehicle'    = '' OR a."vehicleType" = :'vehicle')
    AND (:'size_group' = '' OR a."sizeGroup"   = :'size_group')
),
rolled AS (
  SELECT
    CASE WHEN GROUPING("category") = 1 THEN 'All categories' ELSE "category" END AS category,
    sum("units")::bigint AS units,
    sum("value") AS value,
    GROUPING("category") = 1 AS is_total
  FROM filtered
  GROUP BY ROLLUP ("category")
)
SELECT
  category,
  units,
  value,
  round(100.0 * value / nullif(max(value) FILTER (WHERE is_total) OVER (), 0), 1) AS value_share_pct,
  CASE WHEN NOT is_total THEN RANK() OVER (PARTITION BY is_total ORDER BY value DESC) END AS value_rank,
  is_total
FROM rolled
ORDER BY is_total, value DESC;
