-- R4 Demand Calendar — level: weekday pivot (month rows x day-of-week columns)
-- Is any day of the week busier, and does that pattern hold every month?
-- OLAP: pivot by conditional aggregation (FILTER) — months down the side,
-- Monday..Sunday across the top — plus a ROLLUP grand-total row; slice by
-- period and payday; dice by vehicle and order-size group.
-- Cells are average orders per day (each weekday occurs 4-5 times a month,
-- and partial months have fewer), so cells are comparable.
--
-- Parameters (empty string = all):
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   payday      'yes' | 'no'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   size_group  'Light' | 'Heavy'
--
-- Columns: month_label, mon, tue, wed, thu, fri, sat, sun, all_days, is_total
--   All cells are average orders per day for that month and weekday.

WITH daily AS (
  SELECT d."dateKey", d."year", d."monthNumber", d."monthName",
         extract(isodow FROM d."fullDate")::int AS dow,
         count(f."orderDeliveryKey") AS orders
  FROM "DIM_DATE" d
  LEFT JOIN (
    SELECT f.*
    FROM "FACT_ORDERDELIVERY" f
    JOIN "DIM_RIDER"     r USING ("riderKey")
    JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
    WHERE (:'vehicle'    = '' OR r."vehicleType" = :'vehicle')
      AND (:'size_group' = '' OR s."sizeGroup"   = :'size_group')
  ) f ON f."deliveryDateKey" = d."dateKey"
  WHERE (:'year'    = '' OR d."year"     = nullif(:'year', '')::int)
    AND (:'quarter' = '' OR d."quarter"  = nullif(:'quarter', '')::int)
    AND (:'payday'  = '' OR d."isPayDay" = (:'payday' = 'yes'))
  GROUP BY d."dateKey", d."year", d."monthNumber", d."monthName", d."fullDate"
)
SELECT
  CASE WHEN GROUPING("year", "monthNumber") = 3 THEN 'All months'
       ELSE "year" || ' ' || trim(max("monthName")) END AS month_label,
  round(avg(orders) FILTER (WHERE dow = 1), 1) AS mon,
  round(avg(orders) FILTER (WHERE dow = 2), 1) AS tue,
  round(avg(orders) FILTER (WHERE dow = 3), 1) AS wed,
  round(avg(orders) FILTER (WHERE dow = 4), 1) AS thu,
  round(avg(orders) FILTER (WHERE dow = 5), 1) AS fri,
  round(avg(orders) FILTER (WHERE dow = 6), 1) AS sat,
  round(avg(orders) FILTER (WHERE dow = 7), 1) AS sun,
  round(avg(orders), 1) AS all_days,
  GROUPING("year", "monthNumber") = 3 AS is_total
FROM daily
GROUP BY GROUPING SETS (("year", "monthNumber"), ())
ORDER BY is_total, "year", "monthNumber";
