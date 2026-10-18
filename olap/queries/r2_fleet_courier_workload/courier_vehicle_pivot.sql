-- R2 Fleet, Courier & Rider Workload — level: pivot (couriers x vehicle columns)
-- The cross-tab view: one row per courier, one column per vehicle type.
-- OLAP: pivot by conditional aggregation (FILTER), with a ROLLUP grand-total
-- row; slice by period; dice by courier, vehicle, age band, size group.
-- `measure` switches the cells between total orders and orders per rider,
-- which shows that per-rider workload is even even where totals differ.
--
-- Parameters (empty string = all):
--   measure     'orders' (default) | 'per_rider'
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   month       '1'..'12'
--   courier     'FEDEZ' | 'JNT' | 'LBCD'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   age_band    '18-29' | '30-39' | '40-49' | '50-60'
--   size_group  'Light' | 'Heavy'
--
-- Columns: courier, motorcycle, bicycle, car, trike, total, riders, is_total
--   Cells hold orders (measure 'orders') or orders per rider ('per_rider');
--   a cell with no riders of that vehicle is NULL in 'per_rider'.
-- OPTIMIZED (Strategy C): reads AGG_RIDER_DAY instead of FACT_ORDERDELIVERY; same columns and types.

WITH orders AS (
  SELECT r."riderKey", r."courierName", r."vehicleType", f.orders AS n_orders
  FROM "AGG_RIDER_DAY" f
  JOIN "DIM_RIDER"     r USING ("riderKey")
  JOIN "DIM_DATE"      d ON d."dateKey" = f."deliveryDateKey"
  JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
  WHERE (:'year'       = '' OR d."year"        = nullif(:'year', '')::int)
    AND (:'quarter'    = '' OR d."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'      = '' OR d."monthNumber" = nullif(:'month', '')::int)
    AND (:'courier'    = '' OR r."courierName" = :'courier')
    AND (:'vehicle'    = '' OR r."vehicleType" = :'vehicle')
    AND (:'age_band'   = '' OR r."ageBand"     = :'age_band')
    AND (:'size_group' = '' OR s."sizeGroup"   = :'size_group')
),
pivoted AS (
  SELECT
    CASE WHEN GROUPING("courierName") = 1 THEN 'All couriers' ELSE "courierName" END AS courier,
    coalesce(sum(n_orders) FILTER (WHERE "vehicleType" = 'Motorcycle'), 0)::bigint AS motorcycle_orders,
    coalesce(sum(n_orders) FILTER (WHERE "vehicleType" = 'Bicycle'), 0)::bigint AS bicycle_orders,
    coalesce(sum(n_orders) FILTER (WHERE "vehicleType" = 'Car'), 0)::bigint AS car_orders,
    coalesce(sum(n_orders) FILTER (WHERE "vehicleType" = 'Trike'), 0)::bigint AS trike_orders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Motorcycle') AS motorcycle_riders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Bicycle')    AS bicycle_riders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Car')        AS car_riders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Trike')      AS trike_riders,
    coalesce(sum(n_orders), 0)::bigint AS total_orders,
    count(DISTINCT "riderKey") AS riders,
    GROUPING("courierName") = 1 AS is_total
  FROM orders
  GROUP BY ROLLUP ("courierName")
)
SELECT
  courier,
  CASE WHEN :'measure' = 'per_rider'
       THEN round(motorcycle_orders::numeric / nullif(motorcycle_riders, 0), 0)
       ELSE motorcycle_orders END AS motorcycle,
  CASE WHEN :'measure' = 'per_rider'
       THEN round(bicycle_orders::numeric / nullif(bicycle_riders, 0), 0)
       ELSE bicycle_orders END AS bicycle,
  CASE WHEN :'measure' = 'per_rider'
       THEN round(car_orders::numeric / nullif(car_riders, 0), 0)
       ELSE car_orders END AS car,
  CASE WHEN :'measure' = 'per_rider'
       THEN round(trike_orders::numeric / nullif(trike_riders, 0), 0)
       ELSE trike_orders END AS trike,
  CASE WHEN :'measure' = 'per_rider'
       THEN round(total_orders::numeric / nullif(riders, 0), 0)
       ELSE total_orders END AS total,
  riders,
  is_total
FROM pivoted
ORDER BY is_total, courier;
