# OLAP query benchmark evidence

Produced by `olap/benchmark/run_benchmark.py` against the loaded warehouse.
Every number here comes from a real run; nothing is estimated.

```bash
uv run --project etl python olap/benchmark/run_benchmark.py --label baseline
uv run --project etl python olap/benchmark/run_benchmark.py --label baseline-generic-plan --runs 3 --plan-cache-mode force_generic_plan
```

| Folder | What it is |
|---|---|
| `baseline/` | **The "before" for Step 6.** 18 cases, 1 warm-up + 5 measured runs each, custom plans. |
| `baseline-generic-plan/` | Same cases under `force_generic_plan` (3 runs): shows the slowdown a reused prepared statement causes. |
| `baseline-r2/`, `baseline-r2-check/` | Phase 2 repeats of the baseline (9 runs): same state, used to measure run-to-run noise (18/18 md5 equal). |
| `baseline-r3/` | First run of the Phase 2 session; cold cache, inflated on R1 cases. Not used as the reference. |
| `baseline-r4/` | **Phase 2 reference**: warm, no secondary indexes, default settings, original queries (9 runs). |
| `preagg/`, `config/`, `indexes/` | Each Phase 2 strategy measured alone (see `evidence/optimization-log.md`). |
| `optimized/` | All three strategies together; only R3 and R4-busiest-days rewritten. |
| `optimized-v2/` | Same, with R2 and the remaining R4 queries also rewritten onto `AGG_RIDER_DAY`. 4.90x overall. |
| `optimized-v3/` | **Final state**: all 18 cases rewritten (R1 on `AGG_CATEGORY_PERIOD` / `AGG_PRODUCT_PERIOD`), indexes, `jit=off`, `work_mem=64MB`. Sum of medians 2,066 ms vs 20,625 ms, about 10x. |
| `optimized-v3-defaultcfg/` | Final queries and views with default settings (`jit` on, `work_mem` 4 MB): 4,308 ms. Shows what the config contributes. |
| `ablate-jitonly/`, `ablate-workmemonly/`, `ablate-both-recheck/` | Final state with one or both config settings (4,092 / 2,493 / 2,578 ms). `work_mem` carries the effect. `-both-recheck` is a later re-run of the final config and shows 25% session drift. |
| `iso-default/`, `iso-jit-off-only/`, `iso-workmem-only/`, `iso-both/` | R3-customer-top20 with the **original** query, five indexes present, one config setting at a time. Isolates the config regression. |
| `noidx-default/`, `noidx-jit-off-only/`, `noidx-workmem-only/`, `noidx-both/` | Same, with the indexes dropped: indexes do not change the regression. |

Phase 2 comparison: `uv run --project etl python olap/benchmark/compare_runs.py baseline-r4 preagg config indexes optimized optimized-v2 optimized-v3`
Rewrite equivalence check: `uv run --project etl python olap/benchmark/check_equivalence.py`

Each folder holds `results.json` (environment + every run), `results.csv` (one row
per case, for tables and charts) and `plans/<case>.txt` (`EXPLAIN (ANALYZE, BUFFERS)`).

## Test conditions (baseline, 2026-10-16)

| Item | Value |
|---|---|
| Hardware | Intel Core i7-13620H (10 cores / 16 threads), 15.8 GB RAM, NVMe SSD (Micron 2400, 512 GB) |
| OS / runtime | Windows 11 Home 10.0.26200; Docker 28.4.0 (engine: 16 CPUs, 7.6 GB RAM) |
| Database | PostgreSQL 16.15 (Alpine), default settings: `shared_buffers` 128 MB, `work_mem` 4 MB, `effective_cache_size` 4 GB, 2 parallel workers per gather, JIT on |
| Data | 355 MB warehouse: 1,000,000 orders, 1,999,824 order items, 36,500 rider-days; dimensions 365 / 100 / 100,000 / 100,000 / 10,000 / 4 |
| Indexes | Primary-key and natural-key `UNIQUE` indexes only (15). **No secondary indexes**: the clean floor the DDL defines for this experiment. |
| Method | Fresh read-only connection per case; 1 discarded warm-up, 5 measured runs timed on the client around execute + fetch; median reported; one `EXPLAIN (ANALYZE, BUFFERS)` per case |

## Baseline results (median of 5, ms)

| Case | Median | Rows × cols | Note |
|---|---:|---|---|
| R1-category-all | 865.5 | 10 × 6 | All categories |
| R1-category-dice | 128.3 | 10 × 6 | 2025, Motorcycle, Heavy |
| R1-product-all | 1,264.4 | 99 × 7 | Top 10 products per category |
| R1-product-toys | 353.8 | 11 × 7 | Drill into Toys |
| R2-cube-all | 1,193.4 | 20 × 8 | Courier × vehicle CUBE |
| R2-pivot-orders | 690.3 | 4 × 8 | Pivot, total orders |
| R2-pivot-per-rider-q1 | 215.7 | 4 × 8 | Pivot per rider, 2025 Q1 |
| R2-rider-top20 | 332.1 | 20 × 13 | Top 20 riders |
| R3-deciles-all | 833.2 | 10 × 8 | All customers |
| R3-deciles-dice | 485.1 | 10 × 8 | Female, 2025 |
| **R3-geo-country** | **8,224.1** | 63 × 8 | Top 20 countries × gender, **slowest** |
| R3-geo-city | 66.4 | 44 × 8 | Philippines cities |
| **R3-customer-top20** | **2,536.6** | 20 × 11 | Top 20 customers |
| R4-rollup-all | 234.2 | 21 × 9 | Year > Quarter > Month |
| R4-trend-month | 245.8 | 13 × 8 | Monthly trend |
| R4-trend-day | 242.8 | 365 × 8 | Daily trend |
| R4-weekday-pivot | 219.6 | 14 × 10 | Month × weekday |
| R4-busiest-days | 1,480.6 | 10 × 10 | Top 10 days |

## Bottlenecks found in the plans (inputs for Step 6)

1. **Sorts spill to disk.** With `work_mem` = 4 MB, the heavy aggregates sort on disk
   (`Sort Method: external merge`): R3-geo-country 95 MB across 3 workers,
   R3-customer-top20 ~119 MB, R4-busiest-days 41 MB, R2-cube-all 32 MB. Cause:
   `count(DISTINCT …)` over 2M order lines, which needs a sort per group.
2. **Every case is a full sequential scan of a fact table.** No secondary
   index exists on fact foreign keys or on `DIM_DATE` attributes, so even
   narrow slices (one quarter, one country) read every fact row.
3. **R3 geography recomputes 2M item rows into 4 grouping sets** with distinct
   customer and order counts. It is the clearest candidate for a pre-aggregated
   (per-customer) summary table.
4. **Planner statistics are missing.** `pg_stat_user_tables.n_live_tup` reads 0
   for every table: the warehouse has never been `ANALYZE`d since the bulk load
   (autovacuum had not run), so row estimates rely on defaults.

## Generic-plan hazard (measured)

The filters use the pattern `(:'x' = '' OR column = :'x')`, so one statement
serves every filter combination. When a client reuses a prepared statement,
PostgreSQL can switch to a **generic plan** built without the parameter
values. That plan cannot tell which filters are empty, estimates 1 row
instead of 1,000,000, and picks a nested loop
(`Rows Removed by Join Filter: 364,000,000`):

| Case | Custom plan | Generic plan |
|---|---:|---:|
| R4-trend-month | 245.8 ms | **25,817.4 ms** (105×) |
| R4-trend-day | 242.8 ms | **25,568.9 ms** (105×) |
| R4-busiest-days | 1,480.6 ms | **27,563.2 ms** (19×) |
| R1-product-all | 1,264.4 ms | 3,724.1 ms (3×) |

This first appeared as random 27–30 s outliers in the first baseline attempt
(psycopg prepares a statement after its 5th execution). Consequence for the
API: run report queries with `plan_cache_mode = force_custom_plan`, or without
server-side prepared statements. That is itself an optimization strategy to
report.
