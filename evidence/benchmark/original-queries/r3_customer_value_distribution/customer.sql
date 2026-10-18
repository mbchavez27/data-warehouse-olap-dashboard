-- R3 Customer Value Distribution — level: customer (drill-down to the customer grain)
-- Who are the top customers, and where do they sit in the value distribution?
-- OLAP: drill-down to individual customers within the selected slice/dice;
-- each customer's decile and percentile are computed against everyone in
-- the same slice (NTILE, PERCENT_RANK).
--
-- Parameters (empty string = all):
--   country     e.g. 'Philippines'
--   city        e.g. 'Manila' (use with country: city names repeat across countries)
--   gender      'M' | 'F'
--   decile      '1'..'10'  only customers in this decile (from deciles.sql)
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   top_n       customers returned (default 20)
--
-- Columns: value_rank, customer, country, city, gender, orders, units, value,
--          avg_order_value, decile, value_percentile
--   customer is the username (customer names are synthetic; usernames are
--   the stable identifier shown in the source system).

WITH customer_value AS (
  SELECT
    i."customerKey",
    c."username", c."gender", g."country", g."city",
    count(DISTINCT i."orderNumber") AS orders,
    sum(i."quantity") AS units,
    sum(i."lineValue") AS value
  FROM "FACT_ORDERITEM" i
  JOIN "DIM_CUSTOMER"  c USING ("customerKey")
  JOIN "DIM_GEOGRAPHY" g USING ("geoKey")
  JOIN "DIM_DATE"      d ON d."dateKey" = i."deliveryDateKey"
  WHERE (:'country' = '' OR g."country" = :'country')
    AND (:'city'    = '' OR g."city"    = :'city')
    AND (:'gender'  = '' OR c."gender"  = :'gender')
    AND (:'year'    = '' OR d."year"    = nullif(:'year', '')::int)
    AND (:'quarter' = '' OR d."quarter" = nullif(:'quarter', '')::int)
  GROUP BY i."customerKey", c."username", c."gender", g."country", g."city"
),
ranked AS (
  SELECT
    RANK() OVER (ORDER BY value DESC) AS value_rank,
    "username" AS customer, "country" AS country, "city" AS city, "gender" AS gender,
    orders, units, value,
    round(value / nullif(orders, 0), 2) AS avg_order_value,
    NTILE(10) OVER (ORDER BY value DESC) AS decile,
    round((100 * PERCENT_RANK() OVER (ORDER BY value))::numeric, 1) AS value_percentile
  FROM customer_value
)
SELECT *
FROM ranked
WHERE (:'decile' = '' OR decile = nullif(:'decile', '')::int)
ORDER BY value_rank
LIMIT coalesce(nullif(:'top_n', '')::int, 20);
