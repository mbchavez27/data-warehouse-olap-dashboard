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

WITH filtered AS (
  SELECT p."category", i."quantity", i."lineValue"
  FROM "FACT_ORDERITEM" i
  JOIN "DIM_PRODUCT"   p USING ("productKey")
  JOIN "DIM_DATE"      d ON d."dateKey" = i."deliveryDateKey"
  JOIN "DIM_RIDER"     r USING ("riderKey")
  JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
  WHERE (:'year'       = '' OR d."year"        = nullif(:'year', '')::int)
    AND (:'quarter'    = '' OR d."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'      = '' OR d."monthNumber" = nullif(:'month', '')::int)
    AND (:'vehicle'    = '' OR r."vehicleType" = :'vehicle')
    AND (:'size_group' = '' OR s."sizeGroup"   = :'size_group')
),
rolled AS (
  SELECT
    CASE WHEN GROUPING("category") = 1 THEN 'All categories' ELSE "category" END AS category,
    sum("quantity")  AS units,
    sum("lineValue") AS value,
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
