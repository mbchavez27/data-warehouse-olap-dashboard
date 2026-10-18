-- Phase 1 checks on dw_db (warehouse). Run after the ETL rebuild.
\echo '== W1 key-0 (Unknown) references per fact FK column'
SELECT 'FACT_ORDERDELIVERY' tbl, count(*) FILTER (WHERE "deliveryDateKey"=0) dateKey0, count(*) FILTER (WHERE "riderKey"=0) riderKey0,
       count(*) FILTER (WHERE "geoKey"=0) geoKey0, count(*) FILTER (WHERE "orderSizeKey"=0) sizeKey0, count(*) FILTER (WHERE "customerKey"=0) custKey0, count(*) rows
FROM "FACT_ORDERDELIVERY"
UNION ALL SELECT 'FACT_ORDERITEM', count(*) FILTER (WHERE "deliveryDateKey"=0), count(*) FILTER (WHERE "riderKey"=0),
       count(*) FILTER (WHERE "geoKey"=0), count(*) FILTER (WHERE "orderSizeKey"=0), count(*) FILTER (WHERE "customerKey"=0), count(*) FROM "FACT_ORDERITEM"
UNION ALL SELECT 'FACT_RIDERDAILY', count(*) FILTER (WHERE "dateKey"=0), count(*) FILTER (WHERE "riderKey"=0), NULL, NULL, NULL, count(*) FROM "FACT_RIDERDAILY";
\echo '== W1b productKey 0 (DIM_PRODUCT has an Unknown row?)'
SELECT count(*) FILTER (WHERE "productKey"=0) productKey0_rows FROM "FACT_ORDERITEM";

\echo '== W2 grain uniqueness in the warehouse'
SELECT 'FACT_ORDERDELIVERY (orderNumber)' grain, count(*) rows, count(DISTINCT "orderNumber") distinct_keys FROM "FACT_ORDERDELIVERY";
SELECT 'FACT_ORDERITEM (orderNumber, productKey)' grain, count(*) rows,
       (SELECT count(*) FROM (SELECT DISTINCT "orderNumber","productKey" FROM "FACT_ORDERITEM") x) distinct_keys FROM "FACT_ORDERITEM";
SELECT 'FACT_RIDERDAILY (dateKey, riderKey)' grain, count(*) rows, (SELECT count(*) FROM (SELECT DISTINCT "dateKey","riderKey" FROM "FACT_RIDERDAILY") x) distinct_keys FROM "FACT_RIDERDAILY";

\echo '== W3 constraints actually present on fact tables (PK/UNIQUE/FK/index)'
SELECT conrelid::regclass tbl, contype, pg_get_constraintdef(oid) def FROM pg_constraint
WHERE conrelid::regclass::text IN ('"FACT_ORDERDELIVERY"','"FACT_ORDERITEM"','"FACT_RIDERDAILY"') ORDER BY 1,2,3;
SELECT tablename, indexname FROM pg_indexes WHERE schemaname='public' AND tablename LIKE 'FACT%' ORDER BY 1,2;
