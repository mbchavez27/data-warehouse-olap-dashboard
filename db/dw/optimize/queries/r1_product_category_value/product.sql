-- R1 Product & Category Value — level: product (drill-down Category > Product)
-- Which products lead each category by list-price value?
-- OLAP: drill-down from category to product with a per-category subtotal
-- (ROLLUP); slice by period; dice by vehicle, order-size group and category.
--
-- Parameters (empty string = all):
--   category    e.g. 'Toys'  (empty = every category)
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   month       '1'..'12'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   size_group  'Light' | 'Heavy'
--   top_n       products kept per category (default 10)
--
-- Columns: category, product, units, value, share_of_category_pct,
--          rank_in_category, is_subtotal
--   Top N products per category, plus one 'All products' subtotal row per
--   category (is_subtotal) that covers every product, not only the top N.

-- OPTIMIZED (Strategy C): reads AGG_PRODUCT_PERIOD instead of FACT_ORDERITEM + 4 dimension joins; same columns and types.
WITH filtered AS (
  SELECT a."category", a."productName", a."units", a."value"
  FROM "AGG_PRODUCT_PERIOD" a
  WHERE (:'category'   = '' OR a."category"    = :'category')
    AND (:'year'       = '' OR a."year"        = nullif(:'year', '')::int)
    AND (:'quarter'    = '' OR a."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'      = '' OR a."monthNumber" = nullif(:'month', '')::int)
    AND (:'vehicle'    = '' OR a."vehicleType" = :'vehicle')
    AND (:'size_group' = '' OR a."sizeGroup"   = :'size_group')
),
rolled AS (
  SELECT
    "category" AS category,
    CASE WHEN GROUPING("productName") = 1 THEN 'All products' ELSE "productName" END AS product,
    sum("units")::bigint AS units,
    sum("value") AS value,
    GROUPING("productName") = 1 AS is_subtotal
  FROM filtered
  GROUP BY ROLLUP ("category", "productName")
  HAVING GROUPING("category") = 0
),
ranked AS (
  SELECT
    category, product, units, value, is_subtotal,
    round(100.0 * value / nullif(max(value) FILTER (WHERE is_subtotal)
          OVER (PARTITION BY category), 0), 1) AS share_of_category_pct,
    CASE WHEN NOT is_subtotal THEN
      RANK() OVER (PARTITION BY category, is_subtotal ORDER BY value DESC)
    END AS rank_in_category
  FROM rolled
)
SELECT category, product, units, value, share_of_category_pct, rank_in_category, is_subtotal
FROM ranked
WHERE is_subtotal OR rank_in_category <= coalesce(nullif(:'top_n', '')::int, 10)
ORDER BY category, is_subtotal, value DESC;
