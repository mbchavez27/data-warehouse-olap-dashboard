-- Strategy C: restructuring with pre-aggregated summary tables.
--
-- Two materialized views hold the facts at a coarser grain, so the slow
-- reports aggregate a few hundred thousand rows instead of 1-2 million and
-- skip the large count(DISTINCT ...) sorts.
--
--   AGG_CUSTOMER_PERIOD  FACT_ORDERITEM rolled up to customer x geography x
--                        year x quarter. Serves R3 (deciles, geography,
--                        customer). Every order has exactly one customer,
--                        geography and delivery date, so sum(orders) here
--                        equals count(DISTINCT orderNumber) on the fact.
--   AGG_RIDER_DAY        FACT_ORDERDELIVERY rolled up to delivery date x
--                        rider x order size. Serves R4 busiest days; every
--                        R2/R4 filter (period, rider attributes, size group)
--                        is still answerable at this grain.
--
-- Freshness: the views are snapshots. After every ETL load run
--   REFRESH MATERIALIZED VIEW "AGG_CUSTOMER_PERIOD";
--   REFRESH MATERIALIZED VIEW "AGG_RIDER_DAY";
-- 01_dw_schema.sql drops the fact tables with CASCADE, which drops these
-- views too, so after `run_pipeline.py --rebuild` run this file again.
--
-- Apply (PowerShell):
--   docker cp db/dw/optimize/03_preagg.sql stadvdb-mco1-dw-db:/tmp/run.sql
--   docker exec stadvdb-mco1-dw-db psql -X -U postgres -d dw_db -v ON_ERROR_STOP=1 -f /tmp/run.sql

\timing on

DROP MATERIALIZED VIEW IF EXISTS "AGG_CUSTOMER_PERIOD";
CREATE MATERIALIZED VIEW "AGG_CUSTOMER_PERIOD" AS
SELECT i."customerKey", i."geoKey", d."year", d."quarter",
       count(DISTINCT i."orderNumber") AS orders,
       sum(i."quantity")  AS units,
       sum(i."lineValue") AS value
FROM "FACT_ORDERITEM" i
JOIN "DIM_DATE" d ON d."dateKey" = i."deliveryDateKey"
GROUP BY i."customerKey", i."geoKey", d."year", d."quarter";

DROP MATERIALIZED VIEW IF EXISTS "AGG_RIDER_DAY";
CREATE MATERIALIZED VIEW "AGG_RIDER_DAY" AS
SELECT f."deliveryDateKey", f."riderKey", f."orderSizeKey",
       count(*) AS orders,
       sum(f."totalQuantity") AS units
FROM "FACT_ORDERDELIVERY" f
GROUP BY f."deliveryDateKey", f."riderKey", f."orderSizeKey";

ANALYZE "AGG_CUSTOMER_PERIOD";
ANALYZE "AGG_RIDER_DAY";

-- Sanity: both must reproduce the fact totals exactly.
SELECT
  (SELECT count(*)    FROM "AGG_CUSTOMER_PERIOD") AS customer_period_rows,
  (SELECT sum(orders) FROM "AGG_CUSTOMER_PERIOD") AS customer_period_orders,
  (SELECT sum(value)  FROM "AGG_CUSTOMER_PERIOD") = (SELECT sum("lineValue") FROM "FACT_ORDERITEM") AS value_matches,
  (SELECT count(*)    FROM "AGG_RIDER_DAY") AS rider_day_rows,
  (SELECT sum(orders) FROM "AGG_RIDER_DAY") AS rider_day_orders,
  pg_size_pretty(pg_total_relation_size('"AGG_CUSTOMER_PERIOD"')) AS customer_period_size,
  pg_size_pretty(pg_total_relation_size('"AGG_RIDER_DAY"')) AS rider_day_size;
