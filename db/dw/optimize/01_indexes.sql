-- Strategy A: B-tree indexes on the fact tables' foreign keys.
--
-- The DDL (db/dw/init/01_dw_schema.sql) leaves the facts with primary-key
-- indexes only, so every report reads FACT_ORDERITEM / FACT_ORDERDELIVERY in
-- full. These indexes let a filtered (slice/dice) report reach only its rows.
-- 01_dw_schema.sql drops the tables, so after `run_pipeline.py --rebuild`
-- run this file again. A normal reload TRUNCATEs and keeps them.
--
-- Apply (PowerShell):
--   docker cp db/dw/optimize/01_indexes.sql stadvdb-mco1-dw-db:/tmp/run.sql
--   docker exec stadvdb-mco1-dw-db psql -X -U postgres -d dw_db -v ON_ERROR_STOP=1 -f /tmp/run.sql

\timing on

CREATE INDEX IF NOT EXISTS ix_item_deliverydate     ON "FACT_ORDERITEM" ("deliveryDateKey");
CREATE INDEX IF NOT EXISTS ix_item_customer         ON "FACT_ORDERITEM" ("customerKey");
CREATE INDEX IF NOT EXISTS ix_item_product          ON "FACT_ORDERITEM" ("productKey");
CREATE INDEX IF NOT EXISTS ix_item_geo              ON "FACT_ORDERITEM" ("geoKey");
CREATE INDEX IF NOT EXISTS ix_delivery_deliverydate ON "FACT_ORDERDELIVERY" ("deliveryDateKey");

-- Measured and dropped: ix_item_rider, ix_item_ordersize, ix_delivery_rider,
-- ix_delivery_ordersize had idx_scan = 0 across all 18 cases (see
-- evidence/benchmark/indexes/index-usage.txt). Their DIM_RIDER / DIM_ORDERSIZE
-- joins are small hash joins, which the planner keeps.
DROP INDEX IF EXISTS ix_item_rider;
DROP INDEX IF EXISTS ix_item_ordersize;
DROP INDEX IF EXISTS ix_delivery_rider;
DROP INDEX IF EXISTS ix_delivery_ordersize;

ANALYZE "FACT_ORDERITEM";
ANALYZE "FACT_ORDERDELIVERY";

SELECT indexrelname AS index, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE schemaname = 'public' AND indexrelname LIKE 'ix\_%'
ORDER BY pg_relation_size(indexrelid) DESC;
