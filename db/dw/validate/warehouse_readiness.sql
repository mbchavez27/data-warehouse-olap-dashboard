-- Warehouse readiness gate for dw_db (the machine-readable half of Report R0,
-- Data Quality and Reconciliation). Returns a single JSON row describing the
-- actual warehouse shape plus two server-evaluated verdicts, so every consumer
-- (setup_dw.sh, ETL preflight) shares one source of truth:
--   structurallyReady  9 tables; dim columns 11/9/4/5/6/6; fact columns
--                      10/10/7; 9 PKs; 13 FKs; 5 key-0 Unknown rows; 5
--                      DIM_ORDERSIZE rows (Unknown + 4 bands). Holds before
--                      and after loads, so reloads (--dims, --facts) gate on it.
--   passed             structurallyReady AND 0 fact rows: the pre-load state
--                      that setup_dw.sh and --date require.
-- DIM_DATE row count is reported but never gates either verdict.
-- Key counts are scoped to the 9 warehouse tables, so other tables in the same
-- database (e.g. a test database that also holds source tables) do not skew them.
WITH dw(name) AS (
  SELECT unnest(ARRAY['DIM_DATE','DIM_RIDER','DIM_GEOGRAPHY','DIM_ORDERSIZE','DIM_CUSTOMER','DIM_PRODUCT','FACT_ORDERDELIVERY','FACT_ORDERITEM','FACT_RIDERDAILY'])
),
cols AS (
  SELECT c.table_name AS name, count(*) AS n
  FROM information_schema.columns c JOIN dw ON dw.name = c.table_name
  WHERE c.table_schema = current_schema()
  GROUP BY c.table_name
),
keys AS (
  SELECT
    count(*) FILTER (WHERE con.contype = 'p') AS pk,
    count(*) FILTER (WHERE con.contype = 'f') AS fk
  FROM pg_constraint con
  JOIN pg_class r ON r.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = r.relnamespace
  JOIN dw ON dw.name = r.relname
  WHERE n.nspname = current_schema()
),
shape AS (
  SELECT
    (SELECT count(*) FROM information_schema.tables t JOIN dw ON dw.name = t.table_name
       WHERE t.table_schema = current_schema()) AS table_count,
    (SELECT json_object_agg(name, n) FROM cols) AS column_counts,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'DIM_DATE') AS c_date,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'DIM_RIDER') AS c_rider,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'DIM_GEOGRAPHY') AS c_geo,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'DIM_ORDERSIZE') AS c_size,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'DIM_CUSTOMER') AS c_customer,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'DIM_PRODUCT') AS c_product,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'FACT_ORDERDELIVERY') AS c_delivery,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'FACT_ORDERITEM') AS c_item,
    (SELECT coalesce(n, 0) FROM cols WHERE name = 'FACT_RIDERDAILY') AS c_riderdaily,
    (SELECT pk FROM keys) AS pk_count,
    (SELECT fk FROM keys) AS fk_count,
    (SELECT count(*) FROM "DIM_RIDER" WHERE "riderKey" = 0) AS u_rider,
    (SELECT count(*) FROM "DIM_GEOGRAPHY" WHERE "geoKey" = 0) AS u_geo,
    (SELECT count(*) FROM "DIM_ORDERSIZE" WHERE "orderSizeKey" = 0) AS u_size,
    (SELECT count(*) FROM "DIM_CUSTOMER" WHERE "customerKey" = 0) AS u_customer,
    (SELECT count(*) FROM "DIM_PRODUCT" WHERE "productKey" = 0) AS u_product,
    (SELECT count(*) FROM "DIM_ORDERSIZE") AS size_rows,
    (SELECT count(*) FROM "FACT_ORDERDELIVERY") AS f_delivery,
    (SELECT count(*) FROM "FACT_ORDERITEM") AS f_item,
    (SELECT count(*) FROM "FACT_RIDERDAILY") AS f_riderdaily,
    (SELECT count(*) FROM "DIM_DATE") AS date_rows
),
verdict AS (
  SELECT shape.*,
    (table_count = 9
     AND c_date = 11 AND c_rider = 9 AND c_geo = 4 AND c_size = 5
     AND c_customer = 6 AND c_product = 6
     AND c_delivery = 10 AND c_item = 10 AND c_riderdaily = 7
     AND pk_count = 9 AND fk_count = 13
     AND u_rider = 1 AND u_geo = 1 AND u_size = 1 AND u_customer = 1 AND u_product = 1
     AND size_rows = 5) AS structurally_ready
  FROM shape
)
SELECT json_build_object(
  'tableCount', table_count,
  'columnCounts', column_counts,
  'primaryKeyCount', pk_count,
  'foreignKeyCount', fk_count,
  'unknownRows', u_rider + u_geo + u_size + u_customer + u_product,
  'orderSizeBands', size_rows,
  'factRows', f_delivery + f_item + f_riderdaily,
  'dimDateRows', date_rows,
  'structurallyReady', structurally_ready,
  'passed', structurally_ready AND f_delivery + f_item + f_riderdaily = 0
)::text
FROM verdict;
