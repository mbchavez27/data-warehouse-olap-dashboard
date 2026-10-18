-- R2 Fleet, Courier & Rider Workload — level: rider (drill-down Courier > Vehicle > Rider)
-- Which riders carry the most work, how often are they active, and how high
-- do their peak days go?
-- OLAP: drill-down to the rider grain; drill-across from FACT_ORDERDELIVERY
-- (orders, units) to FACT_RIDERDAILY (active days, peak day) through the
-- shared DIM_RIDER and DIM_DATE; slice by period; dice by courier, vehicle,
-- age band.
--
-- Parameters (empty string = all):
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   month       '1'..'12'
--   courier     'FEDEZ' | 'JNT' | 'LBCD'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   age_band    '18-29' | '30-39' | '40-49' | '50-60'
--   sort        'most' (default, heaviest workload first) | 'least'
--   top_n       riders returned (default 20)
--
-- Columns: workload_rank, rider, courier, vehicle, age_band, orders, units,
--          active_days, calendar_days, utilization_pct,
--          avg_orders_per_active_day, peak_day_orders, workload_percentile
--   workload_rank: 1 = most orders in the selected period.
--   utilization_pct = active days / calendar days (rider-day snapshot).
-- OPTIMIZED (Strategy C): reads AGG_RIDER_DAY instead of FACT_ORDERDELIVERY; same columns and types.

WITH rider_dates AS (
  SELECT d."dateKey"
  FROM "DIM_DATE" d
  WHERE (:'year'    = '' OR d."year"        = nullif(:'year', '')::int)
    AND (:'quarter' = '' OR d."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'   = '' OR d."monthNumber" = nullif(:'month', '')::int)
),
riders AS (
  SELECT r."riderKey", r."fullName", r."courierName", r."vehicleType", r."ageBand"
  FROM "DIM_RIDER" r
  WHERE r."riderKey" <> 0
    AND (:'courier'  = '' OR r."courierName" = :'courier')
    AND (:'vehicle'  = '' OR r."vehicleType" = :'vehicle')
    AND (:'age_band' = '' OR r."ageBand"     = :'age_band')
),
-- Order fact: orders and units per rider in the period.
order_side AS (
  SELECT f."riderKey", sum(f.orders)::bigint AS orders, sum(f.units)::bigint AS units
  FROM "AGG_RIDER_DAY" f
  JOIN rider_dates rdt ON rdt."dateKey" = f."deliveryDateKey"
  GROUP BY f."riderKey"
),
-- Snapshot fact: every rider-day, zero-order days included.
day_side AS (
  SELECT rd."riderKey",
         count(*) AS calendar_days,
         sum(rd."isActiveDay") AS active_days,
         max(rd."ordersDelivered") AS peak_day_orders
  FROM "FACT_RIDERDAILY" rd
  JOIN rider_dates USING ("dateKey")
  GROUP BY rd."riderKey"
),
workload AS (
  SELECT
    r."fullName" AS rider, r."courierName" AS courier, r."vehicleType" AS vehicle,
    r."ageBand" AS age_band,
    coalesce(o.orders, 0) AS orders,
    coalesce(o.units, 0) AS units,
    coalesce(dy.active_days, 0) AS active_days,
    coalesce(dy.calendar_days, 0) AS calendar_days,
    dy.peak_day_orders
  FROM riders r
  LEFT JOIN order_side o USING ("riderKey")
  LEFT JOIN day_side  dy USING ("riderKey")
),
ranked AS (
  SELECT
    RANK() OVER (ORDER BY orders DESC) AS workload_rank,
    rider, courier, vehicle, age_band, orders, units, active_days, calendar_days,
    round(100.0 * active_days / nullif(calendar_days, 0), 1) AS utilization_pct,
    round(orders::numeric / nullif(active_days, 0), 1) AS avg_orders_per_active_day,
    peak_day_orders,
    round((100 * PERCENT_RANK() OVER (ORDER BY orders))::numeric, 1) AS workload_percentile
  FROM workload
)
SELECT *
FROM ranked
ORDER BY
  CASE WHEN :'sort' = 'least' THEN orders END ASC,
  CASE WHEN :'sort' = 'least' THEN NULL ELSE orders END DESC,
  rider
LIMIT coalesce(nullif(:'top_n', '')::int, 20);
