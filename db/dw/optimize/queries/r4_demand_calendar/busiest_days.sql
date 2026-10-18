-- R4 Demand Calendar — level: busiest (or quietest) days
-- Which single days put the most load on the network?
-- OLAP: drill-down to the day grain with a ranking (RANK) and each day's
-- deviation from the average day in the same slice; slice by period,
-- weekend and payday; dice by vehicle and size group.
--
-- Parameters (empty string = all):
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   month       '1'..'12'
--   day_type    'weekday' | 'weekend'
--   payday      'yes' | 'no'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   size_group  'Light' | 'Heavy'
--   sort        'busiest' (default) | 'quietest'
--   top_n       days returned (default 10)
--
-- Columns: demand_rank, date, day_name, is_weekend, is_payday, orders, units,
--          active_riders, orders_per_active_rider, vs_average_pct
--   demand_rank: 1 = most orders. vs_average_pct compares the day with the
--   average day in the selected slice.

-- OPTIMIZED VARIANT: reads AGG_RIDER_DAY (db/dw/optimize/03_preagg.sql)
-- instead of FACT_ORDERDELIVERY. Same columns, types and rows as the original.
WITH daily AS (
  SELECT d."fullDate", trim(d."dayName") AS day_name, d."isWeekend", d."isPayDay",
         coalesce(sum(f.orders), 0)::bigint AS orders,
         coalesce(sum(f.units), 0)::bigint AS units,
         count(DISTINCT f."riderKey") AS active_riders
  FROM "DIM_DATE" d
  LEFT JOIN (
    SELECT f."deliveryDateKey", f."riderKey", f.orders, f.units
    FROM "AGG_RIDER_DAY" f
    JOIN "DIM_RIDER"     r USING ("riderKey")
    JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
    WHERE (:'vehicle'    = '' OR r."vehicleType" = :'vehicle')
      AND (:'size_group' = '' OR s."sizeGroup"   = :'size_group')
  ) f ON f."deliveryDateKey" = d."dateKey"
  WHERE (:'year'     = '' OR d."year"        = nullif(:'year', '')::int)
    AND (:'quarter'  = '' OR d."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'    = '' OR d."monthNumber" = nullif(:'month', '')::int)
    AND (:'day_type' = '' OR d."isWeekend"   = (:'day_type' = 'weekend'))
    AND (:'payday'   = '' OR d."isPayDay"    = (:'payday' = 'yes'))
  GROUP BY d."fullDate", d."dayName", d."isWeekend", d."isPayDay"
),
ranked AS (
  SELECT
    RANK() OVER (ORDER BY orders DESC) AS demand_rank,
    "fullDate" AS date, day_name, "isWeekend" AS is_weekend, "isPayDay" AS is_payday,
    orders, units, active_riders,
    round(orders::numeric / nullif(active_riders, 0), 1) AS orders_per_active_rider,
    round(100.0 * (orders - avg(orders) OVER ()) / nullif(avg(orders) OVER (), 0), 1) AS vs_average_pct
  FROM daily
)
SELECT *
FROM ranked
ORDER BY
  CASE WHEN :'sort' = 'quietest' THEN orders END ASC,
  CASE WHEN :'sort' = 'quietest' THEN NULL ELSE orders END DESC,
  date
LIMIT coalesce(nullif(:'top_n', '')::int, 10);
