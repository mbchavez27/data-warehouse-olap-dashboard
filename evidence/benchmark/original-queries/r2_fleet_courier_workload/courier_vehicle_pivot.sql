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

WITH orders AS (
  SELECT r."riderKey", r."courierName", r."vehicleType"
  FROM "FACT_ORDERDELIVERY" f
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
    count(*) FILTER (WHERE "vehicleType" = 'Motorcycle') AS motorcycle_orders,
    count(*) FILTER (WHERE "vehicleType" = 'Bicycle')    AS bicycle_orders,
    count(*) FILTER (WHERE "vehicleType" = 'Car')        AS car_orders,
    count(*) FILTER (WHERE "vehicleType" = 'Trike')      AS trike_orders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Motorcycle') AS motorcycle_riders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Bicycle')    AS bicycle_riders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Car')        AS car_riders,
    count(DISTINCT "riderKey") FILTER (WHERE "vehicleType" = 'Trike')      AS trike_riders,
    count(*) AS total_orders,
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
