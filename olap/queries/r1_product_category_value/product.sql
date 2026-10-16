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

WITH filtered AS (
  SELECT p."category", p."productName", i."quantity", i."lineValue"
  FROM "FACT_ORDERITEM" i
  JOIN "DIM_PRODUCT"   p USING ("productKey")
  JOIN "DIM_DATE"      d ON d."dateKey" = i."deliveryDateKey"
  JOIN "DIM_RIDER"     r USING ("riderKey")
  JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
  WHERE (:'category'   = '' OR p."category"    = :'category')
    AND (:'year'       = '' OR d."year"        = nullif(:'year', '')::int)
    AND (:'quarter'    = '' OR d."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'      = '' OR d."monthNumber" = nullif(:'month', '')::int)
    AND (:'vehicle'    = '' OR r."vehicleType" = :'vehicle')
    AND (:'size_group' = '' OR s."sizeGroup"   = :'size_group')
),
rolled AS (
  SELECT
    "category" AS category,
    CASE WHEN GROUPING("productName") = 1 THEN 'All products' ELSE "productName" END AS product,
    sum("quantity")  AS units,
    sum("lineValue") AS value,
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
