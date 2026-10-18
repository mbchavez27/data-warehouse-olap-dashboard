-- Phase 1 data checks on source_db. Read-only: run with
--   docker exec -i stadvdb-mco1-source-db psql -U postgres -d source_db -A -F'|' -v ON_ERROR_STOP=1 < source-checks.sql
-- (the session below also sets default_transaction_read_only).
SET default_transaction_read_only = on;

\echo '== S1 deliveryDate formats (the paper says 501,029 ISO + 498,971 US)'
SELECT CASE
         WHEN "deliveryDate" ~ '^\d{4}-\d{2}-\d{2}$' THEN 'YYYY-MM-DD'
         WHEN "deliveryDate" ~ '^\d{2}/\d{2}/\d{4}$' THEN 'MM/DD/YYYY'
         WHEN "deliveryDate" IS NULL THEN 'NULL'
         ELSE 'other' END AS format,
       count(*) AS orders
FROM "Orders" GROUP BY 1 ORDER BY 1;

\echo '== S2 deliveryDate range after parsing, and orders per calendar month'
WITH p AS (
  SELECT CASE WHEN "deliveryDate" ~ '^\d{4}-\d{2}-\d{2}$' THEN to_date("deliveryDate",'YYYY-MM-DD')
              ELSE to_date("deliveryDate",'MM/DD/YYYY') END AS d
  FROM "Orders")
SELECT to_char(date_trunc('month', d),'YYYY-MM') AS month, count(*) AS orders,
       count(DISTINCT d) AS days_present,
       round(count(*)::numeric / count(DISTINCT d), 1) AS orders_per_day
FROM p GROUP BY 1 ORDER BY 1;

\echo '== S3 daily orders: mean, min, max over all days'
WITH p AS (
  SELECT CASE WHEN "deliveryDate" ~ '^\d{4}-\d{2}-\d{2}$' THEN to_date("deliveryDate",'YYYY-MM-DD')
              ELSE to_date("deliveryDate",'MM/DD/YYYY') END AS d
  FROM "Orders"), c AS (SELECT d, count(*) n FROM p GROUP BY d)
SELECT min(d) AS first_day, max(d) AS last_day, count(*) AS days,
       round(avg(n),2) AS mean_per_day, min(n) AS min_day, max(n) AS max_day FROM c;

\echo '== S4 Users.gender raw labels'
SELECT coalesce("gender",'<NULL>') AS label, count(*) FROM "Users" GROUP BY 1 ORDER BY 2 DESC;
\echo '== S5 Riders.gender raw labels'
SELECT coalesce("gender",'<NULL>') AS label, count(*) FROM "Riders" GROUP BY 1 ORDER BY 2 DESC;
\echo '== S6 Riders.vehicleType raw labels'
SELECT coalesce("vehicleType",'<NULL>') AS label, count(*) FROM "Riders" GROUP BY 1 ORDER BY 2 DESC;
\echo '== S7 Products.category raw labels'
SELECT coalesce("category",'<NULL>') AS label, count(*) FROM "Products" GROUP BY 1 ORDER BY 1;
\echo '== S7b distinct category labels / distinct after trim+lower'
SELECT count(DISTINCT "category") AS raw_labels, count(DISTINCT lower(btrim("category"))) AS lower_trim_labels FROM "Products";

\echo '== S8 Rider age: min, max, nulls'
SELECT min("age"), max("age"), count(*) FILTER (WHERE "age" IS NULL) AS null_age, count(*) AS riders FROM "Riders";

\echo '== S9 Products.price: stored scale vs 2-decimal rounding'
SELECT count(*) AS products,
       count(*) FILTER (WHERE "price"::text ~ '\.\d{3,}') AS more_than_2dp,
       count(*) FILTER (WHERE "price" IS NULL) AS null_price,
       count(*) FILTER (WHERE "price" < 0) AS negative_price,
       min("price") AS min_price, max("price") AS max_price FROM "Products";

\echo '== S10 OrderItems.notes and quantity'
SELECT count(*) AS items, count(*) FILTER (WHERE "notes" IS NULL) AS notes_null,
       count(*) FILTER (WHERE "notes" IS NOT NULL) AS notes_not_null,
       min("quantity"), max("quantity"), count(*) FILTER (WHERE "quantity" IS NULL OR "quantity" < 1) AS bad_qty FROM "OrderItems";

\echo '== S11 Name parts (full_name rule): missing first/last'
SELECT 'Users' AS tbl, count(*) FILTER (WHERE btrim(coalesce("firstName",''))='') AS no_first,
       count(*) FILTER (WHERE btrim(coalesce("lastName",''))='') AS no_last FROM "Users"
UNION ALL
SELECT 'Riders', count(*) FILTER (WHERE btrim(coalesce("firstName",''))=''),
       count(*) FILTER (WHERE btrim(coalesce("lastName",''))='') FROM "Riders";

\echo '== S12 Geography/user attribute nulls'
SELECT count(*) AS users, count(*) FILTER (WHERE "country" IS NULL OR btrim("country")='') AS no_country,
       count(*) FILTER (WHERE "city" IS NULL OR btrim("city")='') AS no_city,
       count(*) FILTER (WHERE "zipCode" IS NULL OR btrim("zipCode")='') AS no_zip FROM "Users";

\echo '== S13 Orders referential gaps (source does not declare these FKs)'
SELECT count(*) FILTER (WHERE "userId" IS NULL) AS null_user,
       count(*) FILTER (WHERE "userId" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "Users" u WHERE u."id"=o."userId")) AS orphan_user,
       count(*) FILTER (WHERE "deliveryRiderId" IS NULL) AS null_rider,
       count(*) FILTER (WHERE "deliveryRiderId" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "Riders" r WHERE r."id"=o."deliveryRiderId")) AS orphan_rider
FROM "Orders" o;
SELECT count(*) FILTER (WHERE "courierId" IS NULL) AS null_courier,
       count(*) FILTER (WHERE "courierId" IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "Couriers" c WHERE c."id"=r."courierId")) AS orphan_courier
FROM "Riders" r;

\echo '== S14 Candidate grain uniqueness in the source'
SELECT 'Orders.orderNumber' AS grain, count(*) AS rows, count(DISTINCT "orderNumber") AS distinct_keys,
       count(*) - count(DISTINCT "orderNumber") AS duplicates, count(*) FILTER (WHERE "orderNumber" IS NULL) AS nulls FROM "Orders";
SELECT 'OrderItems(OrderId,ProductId)' AS grain, count(*) AS rows,
       (SELECT count(*) FROM (SELECT DISTINCT "OrderId","ProductId" FROM "OrderItems") x) AS distinct_keys FROM "OrderItems";
SELECT 'Orders(deliveryRiderId,date) rider-days' AS grain, count(*) AS distinct_rider_days FROM (
  SELECT DISTINCT "deliveryRiderId",
    CASE WHEN "deliveryDate" ~ '^\d{4}-\d{2}-\d{2}$' THEN to_date("deliveryDate",'YYYY-MM-DD') ELSE to_date("deliveryDate",'MM/DD/YYYY') END AS d
  FROM "Orders") x;

\echo '== S15 Order line count and total quantity distribution (order-size rule)'
WITH t AS (SELECT "OrderId", count(*) lines, sum("quantity") units FROM "OrderItems" GROUP BY 1)
SELECT count(*) AS orders_with_items, min(units), max(units),
       count(*) FILTER (WHERE units BETWEEN 1 AND 6) AS small_1_6,
       count(*) FILTER (WHERE units BETWEEN 7 AND 10) AS medium_7_10,
       count(*) FILTER (WHERE units BETWEEN 11 AND 15) AS large_11_15,
       count(*) FILTER (WHERE units >= 16) AS bulk_16_plus,
       percentile_disc(0.25) WITHIN GROUP (ORDER BY units) AS q1,
       percentile_disc(0.50) WITHIN GROUP (ORDER BY units) AS q2,
       percentile_disc(0.75) WITHIN GROUP (ORDER BY units) AS q3 FROM t;
SELECT count(*) AS orders_without_items FROM "Orders" o WHERE NOT EXISTS (SELECT 1 FROM "OrderItems" i WHERE i."OrderId"=o."id");
