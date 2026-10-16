-- R2 Fleet, Courier & Rider Workload — level: courier x vehicle (CUBE)
-- How is delivery volume split across couriers and vehicles, and is the work
-- fair per rider?
-- OLAP: CUBE gives every courier x vehicle cell plus every subtotal (per
-- courier, per vehicle, grand total) in one pass, which is the data behind the
-- pivot view; slice by period; dice by courier, vehicle, age band, size group.
--
-- Parameters (empty string = all):
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   month       '1'..'12'
--   courier     'FEDEZ' | 'JNT' | 'LBCD'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   age_band    '18-29' | '30-39' | '40-49' | '50-60'
--   size_group  'Light' | 'Heavy'
--
-- Columns: courier, vehicle, orders, units, riders, orders_per_rider,
--          order_share_pct, grouping_level
--   grouping_level: 0 = courier x vehicle cell, 1 = courier subtotal,
--                   2 = vehicle subtotal, 3 = grand total
--   Subtotal rows read 'All couriers' / 'All vehicles'.

WITH orders AS (
  SELECT r."riderKey", r."courierName", r."vehicleType", f."totalQuantity"
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
cubed AS (
  SELECT
    CASE WHEN GROUPING("courierName") = 1 THEN 'All couriers' ELSE "courierName" END AS courier,
    CASE WHEN GROUPING("vehicleType") = 1 THEN 'All vehicles' ELSE "vehicleType" END AS vehicle,
    count(*) AS orders,
    sum("totalQuantity") AS units,
    count(DISTINCT "riderKey") AS riders,
    GROUPING("courierName", "vehicleType") AS grouping_level
  FROM orders
  GROUP BY CUBE ("courierName", "vehicleType")
)
SELECT
  courier,
  vehicle,
  orders,
  units,
  riders,
  round(orders::numeric / nullif(riders, 0), 0) AS orders_per_rider,
  round(100.0 * orders / nullif(max(orders) FILTER (WHERE grouping_level = 3) OVER (), 0), 1) AS order_share_pct,
  grouping_level
FROM cubed
ORDER BY grouping_level, courier, vehicle;
