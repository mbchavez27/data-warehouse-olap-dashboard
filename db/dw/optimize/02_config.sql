-- Strategy B: per-database planner and executor settings.
--
-- jit = off: the baseline plans spend 0.5-0.6 s compiling expressions for
-- queries that then run in 2-8 s (R3-geo-country, R3-customer-top20).
-- work_mem = 64MB: the sorts behind count(DISTINCT ...), GROUPING SETS and
-- CUBE spill to disk at the 4 MB default ("Sort Method: external merge").
-- The Docker VM has 8 GB, so 64 MB per sort node is safe for this workload.
--
-- These settings live in the cluster catalog and survive a warehouse rebuild.
-- New sessions pick them up; existing ones keep their old values.
-- Rollback:
--   ALTER DATABASE dw_db RESET jit;
--   ALTER DATABASE dw_db RESET work_mem;

ALTER DATABASE dw_db SET jit = off;
ALTER DATABASE dw_db SET work_mem = '64MB';
