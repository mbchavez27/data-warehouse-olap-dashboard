# Query optimization log (MCO1 Phase 2)

Every number comes from `olap/benchmark/run_benchmark.py` (1 warm-up + 9 timed runs, median, fresh
read-only connection per case) and every result set was checked by md5 against the baseline
(`olap/benchmark/compare_runs.py`: 18 cases, **0 mismatches** across all labels). Plans are in
`evidence/benchmark/<label>/plans/`. Run date 2026-10-18, PostgreSQL 16.15 in Docker.

## Strategies

| # | Strategy | Files |
|---|---|---|
| A | Five B-tree indexes on fact foreign keys | `db/dw/optimize/01_indexes.sql` |
| B | `jit = off`, `work_mem = 64MB` on `dw_db` | `db/dw/optimize/02_config.sql` |
| C | Two pre-aggregated materialized views and query rewrites that read them | `db/dw/optimize/03_preagg.sql`, `db/dw/optimize/queries/` |

Labels: `baseline-r4` (no secondary indexes, default settings, original queries; the reference),
`preagg` (C only), `config` (B only), `indexes` (A only), `optimized` (A + B + C).

## Median ms per case (speedup vs `baseline-r4`)

| Case | baseline | C pre-agg | B config | A indexes | A+B+C |
|---|---:|---:|---:|---:|---:|
| R1-category-all | 884.3 | 857.3 (1.03x) | 808.6 (1.09x) | 782.0 (1.13x) | 776.5 (1.14x) |
| R1-category-dice | 322.2 | 283.0 (1.14x) | 272.5 (1.18x) | 280.7 (1.15x) | 281.4 (1.15x) |
| R1-product-all | 1421.5 | 1319.5 (1.08x) | 1163.3 (1.22x) | 1192.7 (1.19x) | 1156.9 (1.23x) |
| R1-product-toys | 468.5 | 369.1 (1.27x) | 360.5 (1.30x) | 342.3 (1.37x) | 356.9 (1.31x) |
| R2-cube-all | 1250.5 | 1320.4 (0.95x) | 923.7 (1.35x) | 1164.4 (1.07x) | 943.1 (1.33x) |
| R2-pivot-orders | 730.8 | 677.2 (1.08x) | 561.9 (1.30x) | 659.0 (1.11x) | 575.0 (1.27x) |
| R2-pivot-per-rider-q1 | 226.6 | 231.4 (0.98x) | 183.7 (1.23x) | 217.6 (1.04x) | 220.3 (1.03x) |
| R2-rider-top20 | 293.2 | 299.2 (0.98x) | 277.3 (1.06x) | 268.9 (1.09x) | 297.8 (0.98x) |
| R3-deciles-all | 717.3 | 269.2 (**2.66x**) | 693.1 (1.03x) | 699.4 (1.03x) | 232.8 (**3.08x**) |
| R3-deciles-dice | 535.8 | 121.8 (**4.40x**) | 510.8 (1.05x) | 475.6 (1.13x) | 121.4 (**4.41x**) |
| R3-geo-country | 8456.2 | 585.5 (**14.44x**) | 7224.8 (1.17x) | 8014.1 (1.06x) | 451.3 (**18.74x**) |
| R3-geo-city | 72.6 | 14.6 (**4.98x**) | 78.1 (0.93x) | 31.1 (2.34x) | 15.8 (**4.60x**) |
| R3-customer-top20 | 2668.7 | 668.2 (**3.99x**) | 3682.0 (**0.72x**) | 2522.5 (1.06x) | 534.0 (**5.00x**) |
| R4-rollup-all | 259.2 | 244.3 (1.06x) | 253.7 (1.02x) | 251.1 (1.03x) | 255.1 (1.02x) |
| R4-trend-month | 261.6 | 249.8 (1.05x) | 270.6 (0.97x) | 259.6 (1.01x) | 249.1 (1.05x) |
| R4-trend-day | 266.4 | 257.8 (1.03x) | 264.7 (1.01x) | 264.4 (1.01x) | 249.2 (1.07x) |
| R4-weekday-pivot | 243.4 | 230.9 (1.05x) | 239.7 (1.02x) | 241.2 (1.01x) | 242.2 (1.00x) |
| R4-busiest-days | 1546.6 | 75.9 (**20.38x**) | 1274.8 (1.21x) | 1024.6 (1.51x) | 64.5 (**24.00x**) |
| **Sum of medians** | **20,625** | **8,075 (2.55x)** | **19,044 (1.08x)** | **18,691 (1.10x)** | **7,023 (2.94x)** |

The three heaviest cases (R3-geo-country, R3-customer-top20, R4-busiest-days) total 12,672 ms
at baseline and 1,050 ms in `optimized`.

## What each strategy did (plan evidence)

**C, pre-aggregation: the main win.** `AGG_CUSTOMER_PERIOD` (383,024 rows, 28 MB) and `AGG_RIDER_DAY`
(145,825 rows, 8.7 MB) replace the full scan of the 2M-row `FACT_ORDERITEM` / 1M-row
`FACT_ORDERDELIVERY` in the five R3 cases and R4-busiest-days. In
`baseline-r4/plans/R3-geo-country.txt` the plan scans the fact table and sorts for
`count(DISTINCT orderNumber)` with three disk sorts; in `preagg/plans/R3-geo-country.txt` there is
no fact scan (`on "AGG_..."` once). Execution time in the plans: R3-geo-country 7,936 -> 578 ms,
R3-customer-top20 2,973 -> 700 ms, R4-busiest-days 1,692 -> 91 ms. The rewrite is exact because
each order has exactly one customer, geography and delivery date (0 violations checked), so
`sum(orders)` on the summary equals `count(DISTINCT orderNumber)` on the fact. md5 confirms it.

**B, config: modest, mostly on the CUBE/pivot/sort-heavy cases.** The baseline plans spend 518 ms
(R3-geo-country) and 871 ms (R3-customer-top20) on JIT compilation. With `work_mem = 64MB`
R3-geo-country no longer spills (3 external merges -> 0). Gains: R2-cube-all 1.35x,
R2-pivot-orders 1.30x, R2-pivot-per-rider-q1 1.23x, R3-geo-country 1.17x.
**Regression:** R3-customer-top20 got slower (2,669 -> 3,682 ms, 0.72x). Its config plan has no
`Gather Merge` and no workers: one 148,848 kB external-merge sort replaced the three parallel worker
sorts of the baseline plan. I did not isolate whether `jit` or `work_mem` triggered the plan change.
In `optimized` the query no longer touches the fact table, so the regression does not show.

**A, indexes: narrow benefit.** Only two cases improved clearly. R3-geo-city 72.6 -> 31.1 ms
(plan: `Index Scan using ix_item_geo` instead of a fact scan) and R4-busiest-days 1,547 -> 1,025 ms
(`Index Scan using ix_delivery_deliverydate`, 365 loops). Everything else stays on sequential scans:
the unfiltered reports read most of each fact table, so an index cannot help. Four more indexes on
rider and order size were built, measured at `idx_scan = 0` over all 18 cases, and dropped
(`evidence/benchmark/indexes/index-usage.txt`). The five that remain add about 63 MB (sizes from the
build log: 15 + 15 + 13 + 13 + 7 MB).

## Costs and risks

- **Freshness.** The views are snapshots. After every ETL load run
  `REFRESH MATERIALIZED VIEW "AGG_CUSTOMER_PERIOD"; REFRESH MATERIALIZED VIEW "AGG_RIDER_DAY";`.
  Build time was 9.5 s and 0.9 s. A `--rebuild` drops the views (and indexes), so re-run the
  `db/dw/optimize` files afterwards. `ALTER DATABASE` settings survive a rebuild.
- **Storage.** Database size 355 MB (baseline) -> 455 MB (all three strategies).
- **Filters not covered.** The rewrites serve the filters the reports expose (year, quarter,
  gender, country, rider and size attributes). A new filter on a column the summary lacks
  (for example product) needs the original query.
- **R4 trend / rollup / weekday pivot and R2-rider-top20 do not improve** (about 250 ms, 1.00x):
  they are single sequential scans that already run in parallel.

## Measurement notes

- Run-to-run noise is up to about 15% (`baseline-r2` vs `baseline-r2-check`, same state, 18/18 md5
  equal). Differences below about 1.15x in the table are not evidence of an effect. The 0.88-0.98x
  entries under `preagg` for R2 cases are noise: those queries are unchanged in that label.
- `baseline-r3` was the first run of the session and is inflated on the R1 cases (cache not warm, for
  example R1-category-all 1,458 ms vs 884 ms). `baseline-r4` was re-run warm in the same session as
  the strategy labels and is the reference above. `baseline-r2` (an earlier session) agrees with
  `baseline-r4` within 10% on 12 of 18 cases, but `baseline-r4` is slower on the rest: R1-category-all
  +18%, R1-category-dice +20%, R1-product-all +20%, R1-product-toys +37%, R3-deciles-dice +25%,
  R2-pivot-orders +12%. Against `baseline-r2`, `optimized` is 0.96-1.02x on the four R1 cases (see
  `compare_runs.py baseline-r2 optimized`). **So the R1 and R2 gains in the table (up to 1.37x) are
  within baseline drift between runs and should not be claimed.** The robust results are the
  R3 cases and R4-busiest-days (3x-24x vs either baseline) and the R3-customer-top20 regression
  under config alone.
- The `indexes` label here (5 indexes) replaces an earlier 9-index run; the four dropped indexes were
  unused.
- Timings include client wall-clock around execute + fetch on the same machine as the Docker VM.
