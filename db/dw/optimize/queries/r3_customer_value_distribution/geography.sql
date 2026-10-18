-- R3 Customer Value Distribution — level: geography (drill-down Country > City)
-- Where are customers and their value concentrated, and how does gender split it?
-- OLAP: GROUPING SETS computes the location rows, the gender split of each
-- location, the overall gender split and the grand total in one pass; drill
-- from countries into one country's cities; dice by gender and period.
--
-- Parameters (empty string = all):
--   level       'country' (default) | 'city'
--   country     required for level 'city' (drill into that country)
--   gender      'M' | 'F'
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--   top_n       locations returned (default 20)
--
-- Columns: location, gender, customers, orders, value, value_per_customer,
--          value_rank, grouping_level
--   grouping_level: 0 = location x gender, 1 = location total,
--                   2 = gender total across locations, 3 = grand total
--   location reads 'All locations' and gender 'All' on subtotal rows.
--   City names repeat across countries, so level 'city' always works inside
--   one country.

-- OPTIMIZED VARIANT: reads AGG_CUSTOMER_PERIOD (db/dw/optimize/03_preagg.sql)
-- instead of FACT_ORDERITEM. Same columns, types and rows as the original.
WITH filtered AS (
  SELECT
    CASE WHEN :'level' = 'city' THEN g."city" ELSE g."country" END AS location,
    c."gender", i."customerKey", i.orders, i.value
  FROM "AGG_CUSTOMER_PERIOD" i
  JOIN "DIM_CUSTOMER"  c USING ("customerKey")
  JOIN "DIM_GEOGRAPHY" g USING ("geoKey")
  WHERE (:'country' = '' OR g."country" = :'country')
    AND (:'gender'  = '' OR c."gender"  = :'gender')
    AND (:'year'    = '' OR i."year"    = nullif(:'year', '')::int)
    AND (:'quarter' = '' OR i."quarter" = nullif(:'quarter', '')::int)
    AND (:'level' <> 'city' OR :'country' <> '')
),
grouped AS (
  SELECT
    CASE WHEN GROUPING(location) = 1 THEN 'All locations' ELSE location END AS location,
    CASE WHEN GROUPING("gender") = 1 THEN 'All' ELSE "gender" END AS gender,
    count(DISTINCT "customerKey") AS customers,
    sum(orders)::bigint AS orders,
    sum(value) AS value,
    GROUPING(location, "gender") AS grouping_level
  FROM filtered
  GROUP BY GROUPING SETS ((location, "gender"), (location), ("gender"), ())
),
ranked AS (
  SELECT
    location, gender, customers, orders, value,
    round(value / nullif(customers, 0), 2) AS value_per_customer,
    CASE WHEN grouping_level = 1 THEN
      RANK() OVER (PARTITION BY grouping_level ORDER BY value DESC)
    END AS value_rank,
    grouping_level
  FROM grouped
),
top_locations AS (
  SELECT location FROM ranked
  WHERE grouping_level = 1 AND value_rank <= coalesce(nullif(:'top_n', '')::int, 20)
)
SELECT r.location, r.gender, r.customers, r.orders, r.value, r.value_per_customer,
       max(r.value_rank) OVER (PARTITION BY r.location) AS value_rank,
       r.grouping_level
FROM ranked r
WHERE r.grouping_level >= 2
   OR r.location IN (SELECT location FROM top_locations)
ORDER BY
  r.grouping_level >= 2,
  max(r.value_rank) OVER (PARTITION BY r.location),
  r.grouping_level DESC,
  r.gender = 'All' DESC,
  r.gender;
