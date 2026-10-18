-- R4 Demand Calendar — level: trend (Year > Quarter > Month > Week > Day)
-- How does order demand move over time, and do weekends or paydays differ?
-- OLAP: roll-up / drill-down along the date hierarchy chosen by `level`;
-- slice by period, weekend and payday; dice by vehicle and order-size group.
-- Each period is normalized to orders per calendar day, because the first
-- and last months of the data are partial (Sep 2024 has 7 days, Sep 2025 23)
-- and calendar week 53 is a 1-2 day stub.
--
-- Parameters (empty string = all):
--   level       'year' | 'quarter' | 'month' (default) | 'week' | 'day'
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   month       '1'..'12'
--   day_type    'weekday' | 'weekend'
--   payday      'yes' | 'no'
--   vehicle     'Bicycle' | 'Motorcycle' | 'Car' | 'Trike'
--   size_group  'Light' | 'Heavy'
--
-- Columns: period_label, period_start, days, orders, units, orders_per_day,
--          change_vs_previous_pct, moving_avg_orders_per_day
--   change_vs_previous_pct compares orders_per_day with the previous period
--   (LAG). moving_avg_orders_per_day averages orders_per_day over the
--   current and previous 6 periods (a 7-day average at level 'day').
--   `days` counts calendar days in the period that pass the day filters,
--   including days with no matching orders.

WITH days AS (
  SELECT d.*
  FROM "DIM_DATE" d
  WHERE (:'year'     = '' OR d."year"        = nullif(:'year', '')::int)
    AND (:'quarter'  = '' OR d."quarter"     = nullif(:'quarter', '')::int)
    AND (:'month'    = '' OR d."monthNumber" = nullif(:'month', '')::int)
    AND (:'day_type' = '' OR d."isWeekend"   = (:'day_type' = 'weekend'))
    AND (:'payday'   = '' OR d."isPayDay"    = (:'payday' = 'yes'))
),
daily AS (
  SELECT
    dy."dateKey", dy."fullDate", dy."year", dy."quarter", dy."monthNumber",
    dy."monthName", dy."weekOfYear",
    count(f."orderDeliveryKey") AS orders,
    coalesce(sum(f."totalQuantity"), 0) AS units
  FROM days dy
  LEFT JOIN (
    SELECT f.*
    FROM "FACT_ORDERDELIVERY" f
    JOIN "DIM_RIDER"     r USING ("riderKey")
    JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
    WHERE (:'vehicle'    = '' OR r."vehicleType" = :'vehicle')
      AND (:'size_group' = '' OR s."sizeGroup"   = :'size_group')
  ) f ON f."deliveryDateKey" = dy."dateKey"
  GROUP BY dy."dateKey", dy."fullDate", dy."year", dy."quarter", dy."monthNumber",
           dy."monthName", dy."weekOfYear"
),
periods AS (
  SELECT
    CASE :'level'
      WHEN 'year'    THEN "year"::text
      WHEN 'quarter' THEN "year" || ' Q' || "quarter"
      WHEN 'week'    THEN "year" || ' W' || lpad("weekOfYear"::text, 2, '0')
      WHEN 'day'     THEN to_char("fullDate", 'YYYY-MM-DD')
      ELSE "year" || ' ' || trim("monthName")
    END AS period_label,
    min("fullDate") AS period_start,
    count(*) AS days,
    sum(orders) AS orders,
    sum(units) AS units
  FROM daily
  WHERE :'level' IN ('', 'year', 'quarter', 'month', 'week', 'day')
  GROUP BY
    "year",
    CASE WHEN :'level' IN ('quarter', 'month', 'week', 'day') THEN "quarter" END,
    CASE WHEN :'level' IN ('', 'month', 'day') THEN "monthNumber" END,
    CASE WHEN :'level' = 'week' THEN "weekOfYear" END,
    CASE WHEN :'level' = 'day' THEN "fullDate" END,
    1
),
normalized AS (
  SELECT *, round(orders::numeric / nullif(days, 0), 1) AS orders_per_day
  FROM periods
)
SELECT
  period_label,
  period_start,
  days,
  orders,
  units,
  orders_per_day,
  round(100.0 * (orders_per_day - LAG(orders_per_day) OVER w)
        / nullif(LAG(orders_per_day) OVER w, 0), 1) AS change_vs_previous_pct,
  round(avg(orders_per_day) OVER (ORDER BY period_start ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1)
    AS moving_avg_orders_per_day
FROM normalized
WINDOW w AS (ORDER BY period_start)
ORDER BY period_start;
