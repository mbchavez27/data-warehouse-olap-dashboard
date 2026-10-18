-- R3 Customer Value Distribution — level: deciles (top of Deciles > Country > City > Customer)
-- How concentrated is customer value?
-- OLAP: every customer is ranked into ten equal groups by list-price value
-- (NTILE), then each decile's share and the running (Pareto) share are
-- computed with window functions; dice by country, gender and period.
--
-- Parameters (empty string = all):
--   country     e.g. 'Philippines'
--   gender      'M' | 'F'
--   year        '2024' | '2025'
--   quarter     '1'..'4'
--
-- Columns: decile, customers, value, value_share_pct, cumulative_share_pct,
--          avg_value_per_customer, min_customer_value, max_customer_value
--   Decile 1 = the top 10% of customers by value.

WITH customer_value AS (
  SELECT i."customerKey", sum(i."lineValue") AS value
  FROM "FACT_ORDERITEM" i
  JOIN "DIM_CUSTOMER"  c USING ("customerKey")
  JOIN "DIM_GEOGRAPHY" g USING ("geoKey")
  JOIN "DIM_DATE"      d ON d."dateKey" = i."deliveryDateKey"
  WHERE (:'country' = '' OR g."country" = :'country')
    AND (:'gender'  = '' OR c."gender"  = :'gender')
    AND (:'year'    = '' OR d."year"    = nullif(:'year', '')::int)
    AND (:'quarter' = '' OR d."quarter" = nullif(:'quarter', '')::int)
  GROUP BY i."customerKey"
),
ranked AS (
  SELECT value, NTILE(10) OVER (ORDER BY value DESC) AS decile
  FROM customer_value
),
deciles AS (
  SELECT decile, count(*) AS customers, sum(value) AS value,
         min(value) AS min_customer_value, max(value) AS max_customer_value
  FROM ranked
  GROUP BY decile
)
SELECT
  decile,
  customers,
  value,
  round(100.0 * value / sum(value) OVER (), 1) AS value_share_pct,
  round(100.0 * sum(value) OVER (ORDER BY decile) / sum(value) OVER (), 1) AS cumulative_share_pct,
  round(value / customers, 2) AS avg_value_per_customer,
  min_customer_value,
  max_customer_value
FROM deciles
ORDER BY decile;
