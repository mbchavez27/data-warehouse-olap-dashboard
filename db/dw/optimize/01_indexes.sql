-- Strategy A (fact foreign-key indexes): measured, then retired.
--
-- Five B-tree indexes were tried on the fact foreign keys (deliveryDateKey,
-- customerKey, productKey, geoKey on FACT_ORDERITEM; deliveryDateKey on
-- FACT_ORDERDELIVERY), plus four more on riderKey / orderSizeKey. They only helped
-- the original queries, and only slightly. Every final-state query reads a
-- materialized view (03_preagg.sql), and none of the five is used by any final
-- plan (evidence/benchmark/optimized-v3 and optimized-v3-defaultcfg). The
-- rider/order-size four had idx_scan = 0 across all 18 cases
-- (evidence/benchmark/indexes/index-usage.txt). Indexes make no difference to the
-- R3-customer-top20 regression either (evidence/benchmark/iso-* vs noidx-*).
-- The five fact indexes take about 64 MB and slow every load, so they are not
-- kept. The measurements stay in evidence/optimization-log.md.
--
-- This file now only removes them, so applying it brings an older database into
-- line with the final state. It is safe to run on a database that never had them.
--
-- Apply (PowerShell):
--   docker cp db/dw/optimize/01_indexes.sql stadvdb-mco1-dw-db:/tmp/run.sql
--   docker exec stadvdb-mco1-dw-db psql -X -U postgres -d dw_db -v ON_ERROR_STOP=1 -f /tmp/run.sql

\timing on

DROP INDEX IF EXISTS ix_item_deliverydate;
DROP INDEX IF EXISTS ix_item_customer;
DROP INDEX IF EXISTS ix_item_product;
DROP INDEX IF EXISTS ix_item_geo;
DROP INDEX IF EXISTS ix_delivery_deliverydate;
DROP INDEX IF EXISTS ix_item_rider;
DROP INDEX IF EXISTS ix_item_ordersize;
DROP INDEX IF EXISTS ix_delivery_rider;
DROP INDEX IF EXISTS ix_delivery_ordersize;

ANALYZE "FACT_ORDERITEM";
ANALYZE "FACT_ORDERDELIVERY";

-- Remaining secondary indexes (expected: none).
SELECT indexrelname AS index, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE schemaname = 'public' AND indexrelname LIKE 'ix\_%'
ORDER BY pg_relation_size(indexrelid) DESC;
