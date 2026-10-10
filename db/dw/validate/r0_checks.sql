-- R0 pre-ETL gate for dw_db. Returns a single JSON row describing the actual
-- warehouse shape plus a server-evaluated `passed` flag, so every consumer
-- (setup_dw.sh today, ETL preflight tomorrow) shares one source of truth.
-- Expectations mirror docs/database/data-warehouse-implementation.md:
-- 9 tables; dim columns 11/9/4/5/6/6; fact columns 10/10/7; 9 PKs; 13 FKs;
-- 5 key-0 Unknown rows (+ 4 static order-size bands); 0 fact rows; DIM_DATE
-- empty (its range derives from source deliveryDate at ETL time).
SELECT json_build_object(
  'tableCount', (SELECT count(*) FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = ANY (ARRAY['DIM_DATE','DIM_RIDER','DIM_GEOGRAPHY','DIM_ORDERSIZE','DIM_CUSTOMER','DIM_PRODUCT','FACT_ORDERDELIVERY','FACT_ORDERITEM','FACT_RIDERDAILY'])),
  'columnCounts', json_build_object(
    'DIM_DATE', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_DATE'),
    'DIM_RIDER', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_RIDER'),
    'DIM_GEOGRAPHY', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_GEOGRAPHY'),
    'DIM_ORDERSIZE', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_ORDERSIZE'),
    'DIM_CUSTOMER', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_CUSTOMER'),
    'DIM_PRODUCT', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_PRODUCT'),
    'FACT_ORDERDELIVERY', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'FACT_ORDERDELIVERY'),
    'FACT_ORDERITEM', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'FACT_ORDERITEM'),
    'FACT_RIDERDAILY', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'FACT_RIDERDAILY')
  ),
  'primaryKeyCount', (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND r.relname = ANY (ARRAY['DIM_DATE','DIM_RIDER','DIM_GEOGRAPHY','DIM_ORDERSIZE','DIM_CUSTOMER','DIM_PRODUCT','FACT_ORDERDELIVERY','FACT_ORDERITEM','FACT_RIDERDAILY']) AND c.contype = 'p'),
  'foreignKeyCount', (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND r.relname = ANY (ARRAY['DIM_DATE','DIM_RIDER','DIM_GEOGRAPHY','DIM_ORDERSIZE','DIM_CUSTOMER','DIM_PRODUCT','FACT_ORDERDELIVERY','FACT_ORDERITEM','FACT_RIDERDAILY']) AND c.contype = 'f'),
  'unknownRows', (
    (SELECT count(*) FROM "DIM_RIDER" WHERE "riderKey" = 0)
    + (SELECT count(*) FROM "DIM_GEOGRAPHY" WHERE "geoKey" = 0)
    + (SELECT count(*) FROM "DIM_ORDERSIZE" WHERE "orderSizeKey" = 0)
    + (SELECT count(*) FROM "DIM_CUSTOMER" WHERE "customerKey" = 0)
    + (SELECT count(*) FROM "DIM_PRODUCT" WHERE "productKey" = 0)
  ),
  'orderSizeBands', (SELECT count(*) FROM "DIM_ORDERSIZE"),
  'factRows', (
    (SELECT count(*) FROM "FACT_ORDERDELIVERY")
    + (SELECT count(*) FROM "FACT_ORDERITEM")
    + (SELECT count(*) FROM "FACT_RIDERDAILY")
  ),
  'dimDateRows', (SELECT count(*) FROM "DIM_DATE"),
  'passed', (
    (SELECT count(*) FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_name = ANY (ARRAY['DIM_DATE','DIM_RIDER','DIM_GEOGRAPHY','DIM_ORDERSIZE','DIM_CUSTOMER','DIM_PRODUCT','FACT_ORDERDELIVERY','FACT_ORDERITEM','FACT_RIDERDAILY'])) = 9
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_DATE') = 11
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_RIDER') = 9
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_GEOGRAPHY') = 4
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_ORDERSIZE') = 5
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_CUSTOMER') = 6
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'DIM_PRODUCT') = 6
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'FACT_ORDERDELIVERY') = 10
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'FACT_ORDERITEM') = 10
    AND (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'FACT_RIDERDAILY') = 7
    AND (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND c.contype = 'p') = 9
    AND (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND c.contype = 'f') = 13
    AND (SELECT count(*) FROM "DIM_RIDER" WHERE "riderKey" = 0) = 1
    AND (SELECT count(*) FROM "DIM_GEOGRAPHY" WHERE "geoKey" = 0) = 1
    AND (SELECT count(*) FROM "DIM_ORDERSIZE" WHERE "orderSizeKey" = 0) = 1
    AND (SELECT count(*) FROM "DIM_CUSTOMER" WHERE "customerKey" = 0) = 1
    AND (SELECT count(*) FROM "DIM_PRODUCT" WHERE "productKey" = 0) = 1
    AND (SELECT count(*) FROM "DIM_ORDERSIZE") = 5
    AND (SELECT count(*) FROM "FACT_ORDERDELIVERY") = 0
    AND (SELECT count(*) FROM "FACT_ORDERITEM") = 0
    AND (SELECT count(*) FROM "FACT_RIDERDAILY") = 0
    AND (SELECT count(*) FROM "DIM_DATE") = 0
  )
)::text;
