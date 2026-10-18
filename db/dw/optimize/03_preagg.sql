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
--                        rider x order size. Serves R2 and R4; every
--                        R2/R4 filter (period, rider attributes, size group)
--                        is still answerable at this grain.
--   AGG_CATEGORY_PERIOD  FACT_ORDERITEM rolled up to category x year x quarter
--                        x month x vehicle x size group (936 rows). Serves R1
--                        category. All R1 filters are on these columns.
--   AGG_PRODUCT_PERIOD   FACT_ORDERITEM rolled up to product x the same
--                        period, vehicle and size columns (755,042 rows).
--                        Serves R1 product. It is much larger (76 MB) because
--                        product name is a grain column, but it still removes
--                        the fact scan and the dimension joins.
--
-- Freshness: the views are snapshots. After every ETL load run
--   REFRESH MATERIALIZED VIEW "AGG_CUSTOMER_PERIOD";
--   REFRESH MATERIALIZED VIEW "AGG_RIDER_DAY";
--   REFRESH MATERIALIZED VIEW "AGG_CATEGORY_PERIOD";
--   REFRESH MATERIALIZED VIEW "AGG_PRODUCT_PERIOD";
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

DROP MATERIALIZED VIEW IF EXISTS "AGG_CATEGORY_PERIOD";
CREATE MATERIALIZED VIEW "AGG_CATEGORY_PERIOD" AS
SELECT p."category", d."year", d."quarter", d."monthNumber",
       r."vehicleType", s."sizeGroup",
       sum(i."quantity")  AS units,
       sum(i."lineValue") AS value
FROM "FACT_ORDERITEM" i
JOIN "DIM_PRODUCT"   p USING ("productKey")
JOIN "DIM_DATE"      d ON d."dateKey" = i."deliveryDateKey"
JOIN "DIM_RIDER"     r USING ("riderKey")
JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
GROUP BY p."category", d."year", d."quarter", d."monthNumber", r."vehicleType", s."sizeGroup";

DROP MATERIALIZED VIEW IF EXISTS "AGG_PRODUCT_PERIOD";
CREATE MATERIALIZED VIEW "AGG_PRODUCT_PERIOD" AS
SELECT p."category", p."productName", d."year", d."quarter", d."monthNumber",
       r."vehicleType", s."sizeGroup",
       sum(i."quantity")  AS units,
       sum(i."lineValue") AS value
FROM "FACT_ORDERITEM" i
JOIN "DIM_PRODUCT"   p USING ("productKey")
JOIN "DIM_DATE"      d ON d."dateKey" = i."deliveryDateKey"
JOIN "DIM_RIDER"     r USING ("riderKey")
JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey")
GROUP BY p."category", p."productName", d."year", d."quarter", d."monthNumber", r."vehicleType", s."sizeGroup";

ANALYZE "AGG_CUSTOMER_PERIOD";
ANALYZE "AGG_RIDER_DAY";
ANALYZE "AGG_CATEGORY_PERIOD";
ANALYZE "AGG_PRODUCT_PERIOD";

-- Sanity: each must reproduce the fact totals exactly.
SELECT
  (SELECT count(*)    FROM "AGG_CUSTOMER_PERIOD") AS customer_period_rows,
  (SELECT sum(orders) FROM "AGG_CUSTOMER_PERIOD") AS customer_period_orders,
  (SELECT sum(value)  FROM "AGG_CUSTOMER_PERIOD") = (SELECT sum("lineValue") FROM "FACT_ORDERITEM") AS value_matches,
  (SELECT count(*)    FROM "AGG_RIDER_DAY") AS rider_day_rows,
  (SELECT sum(orders) FROM "AGG_RIDER_DAY") AS rider_day_orders,
  (SELECT sum(value)  FROM "AGG_CATEGORY_PERIOD") = (SELECT sum("lineValue") FROM "FACT_ORDERITEM") AS category_value_matches,
  (SELECT sum(value)  FROM "AGG_PRODUCT_PERIOD") = (SELECT sum("lineValue") FROM "FACT_ORDERITEM") AS product_value_matches,
  (SELECT sum(units)  FROM "AGG_PRODUCT_PERIOD") = (SELECT sum(quantity) FROM "FACT_ORDERITEM") AS product_units_match,
  pg_size_pretty(pg_total_relation_size('"AGG_CUSTOMER_PERIOD"')) AS customer_period_size,
  pg_size_pretty(pg_total_relation_size('"AGG_RIDER_DAY"')) AS rider_day_size,
  pg_size_pretty(pg_total_relation_size('"AGG_CATEGORY_PERIOD"')) AS category_period_size,
  pg_size_pretty(pg_total_relation_size('"AGG_PRODUCT_PERIOD"')) AS product_period_size;
