-- R4 Demand Calendar — level: rollup (Year > Quarter > Month subtotals in one result)
-- The whole date hierarchy at once: every month, its quarter subtotal, its
-- year subtotal and the grand total, each normalized to orders per day.
-- OLAP: roll-up via ROLLUP(year, quarter, month), with GROUPING() naming
-- each row's level; slice by weekend and payday; dice by vehicle and size group.
--
-- Parameters (empty string = all):
--   year        '2024' | '2025'
--   day_type    'weekday' | 'weekend'
--   payday      'yes' | 'no'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   size_group  'Light' | 'Heavy'
--
-- Columns: hierarchy_level, year, quarter, month, month_name, days, orders,
--          units, orders_per_day
--   hierarchy_level: 'month' | 'quarter' | 'year' | 'all'
-- OPTIMIZED (Strategy C): reads AGG_RIDER_DAY instead of FACT_ORDERDELIVERY; same columns and types.

WITH daily AS (
  SELECT d."dateKey", d."year", d."quarter", d."monthNumber", d."monthName",
         coalesce(sum(f.orders), 0)::bigint AS orders,
         coalesce(sum(f.units), 0)::bigint AS units
  FROM "DIM_DATE" d
  LEFT JOIN (
    SELECT f."deliveryDateKey", f.orders, f.units
    FROM "AGG_RIDER_DAY" f
    JOIN "DIM_RIDER"     r USING ("riderKey")
    JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
    WHERE (:'vehicle'    = '' OR r."vehicleType" = :'vehicle')
      AND (:'size_group' = '' OR s."sizeGroup"   = :'size_group')
  ) f ON f."deliveryDateKey" = d."dateKey"
  WHERE (:'year'     = '' OR d."year"      = nullif(:'year', '')::int)
    AND (:'day_type' = '' OR d."isWeekend" = (:'day_type' = 'weekend'))
    AND (:'payday'   = '' OR d."isPayDay"  = (:'payday' = 'yes'))
  GROUP BY d."dateKey", d."year", d."quarter", d."monthNumber", d."monthName"
)
SELECT
  CASE GROUPING("year", "quarter", "monthNumber")
    WHEN 0 THEN 'month' WHEN 1 THEN 'quarter' WHEN 3 THEN 'year' ELSE 'all'
  END AS hierarchy_level,
  "year" AS year,
  "quarter" AS quarter,
  "monthNumber" AS month,
  CASE WHEN GROUPING("monthNumber") = 0 THEN trim(max("monthName")) END AS month_name,
  count(*) AS days,
  sum(orders) AS orders,
  sum(units) AS units,
  round(sum(orders)::numeric / nullif(count(*), 0), 1) AS orders_per_day
FROM daily
GROUP BY ROLLUP ("year", "quarter", "monthNumber")
ORDER BY "year" NULLS LAST, "quarter" NULLS LAST, "monthNumber" NULLS LAST;
