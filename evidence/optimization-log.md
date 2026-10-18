# Query optimization log (MCO1 Phase 2)

Every number comes from `olap/benchmark/run_benchmark.py` (1 warm-up + 9 timed runs, median, fresh
read-only connection per case). Every result set was checked by md5 against the baseline
(`olap/benchmark/compare_runs.py`: 18 cases, **0 mismatches** in every optimized label), and the
rewritten queries were checked against their originals on 1,600 randomized filter combinations
(`olap/benchmark/check_equivalence.py`): **0 mismatches**. Plans are in
`evidence/benchmark/<label>/plans/`. Run date 2026-10-18, PostgreSQL 16.15 in Docker.

**Headline.** Sum of medians over the 18 report cases: 20,625 ms (`baseline-r4`) -> **2,066 ms**
(`optimized-v3`), about **10x**. Against the less-slow earlier baseline (`baseline-r2`, 19,253 ms) it is
9.3x. A re-run of the same configuration (`ablate-both-recheck`) gave 2,578 ms, so the same state
drifts about 25% between sessions. Quote the range, **8-10x**, not a single figure.

## Strategies

| # | Strategy | Files | Used by the final (rewritten) queries? |
|---|---|---|---|
| A | Five B-tree indexes on fact foreign keys (**retired**) | `db/dw/optimize/01_indexes.sql` (now only drops them) | No. No plan in `optimized-v3` or `optimized-v3-defaultcfg` references them. They helped only the original queries (R3-geo-city, R4-busiest-days). The `optimized-v3` runs had them present; they are removed from the applied set because no final plan uses them. |
| B | `jit = off`, `work_mem = 64MB` on `dw_db` | `db/dw/optimize/02_config.sql` | Yes. `work_mem` carries it (see the ablation). |
| C | Four materialized views and query rewrites that read them | `db/dw/optimize/03_preagg.sql`, `db/dw/optimize/queries/` | Yes. This is the main win. |

Apply and refresh all three with `db/scripts/apply_optimizations.sh`.

> **Update (2026-10-18):** the ETL pipeline now applies the same three files after every load, as its
> `--optimize` phase (`etl/load/summaries.py`, over the ETL's own connection, in one transaction that
> checks each view against the facts). The freshness and "required step" risks below are handled by
> the pipeline; the script remains for refreshing by hand.

Labels:
- `baseline-r4`: no secondary indexes, default settings, original queries. The reference.
- `preagg`, `config`, `indexes`: each strategy alone, from the first round.
- `optimized`: A + B + C, with R3 and R4-busiest-days rewritten. `optimized-v2`: adds R2 and the other R4 cases.
- `optimized-v3`: final state. All 18 cases use the optimized queries. Indexes, `jit=off`, `work_mem=64MB`, four views.
- `optimized-v3-defaultcfg`: the same queries and views with default settings (`jit` on, `work_mem` 4 MB).
- `ablate-jitonly`, `ablate-workmemonly`, `ablate-both-recheck`: the final state with one or both config settings.
- `iso-*` and `noidx-*`: the R3-customer-top20 regression isolated (see below).

## Final state vs baseline (median ms, `baseline-r4` vs `optimized-v3`)

| Case | baseline-r4 | optimized-v3 | Speedup | optimized-v3-defaultcfg |
|---|---:|---:|---:|---:|
| R1-category-all | 884.3 | 0.9 | sub-ms, ratio not meaningful | 0.9 |
| R1-category-dice | 322.2 | 0.7 | sub-ms, ratio not meaningful | 0.8 |
| R1-product-all | 1421.5 | 303.4 | 4.7x | 1297.2 |
| R1-product-toys | 468.5 | 94.0 | 5.0x | 201.5 |
| R2-cube-all | 1250.5 | 99.6 | 12.6x | 171.1 |
| R2-pivot-orders | 730.8 | 63.4 | 11.5x | 102.3 |
| R2-pivot-per-rider-q1 | 226.6 | 25.2 | 9.0x | 33.3 |
| R2-rider-top20 | 293.2 | 34.9 | 8.4x | 63.4 |
| R3-deciles-all | 717.3 | 212.1 | 3.4x | 316.3 |
| R3-deciles-dice | 535.8 | 117.5 | 4.6x | 161.0 |
| R3-geo-country | 8456.2 | 405.7 | 20.8x | 741.6 |
| R3-geo-city | 72.6 | 14.3 | 5.1x | 19.3 |
| R3-customer-top20 | 2668.7 | 505.6 | 5.3x | 812.0 |
| R4-rollup-all | 259.2 | 31.9 | 8.1x | 40.0 |
| R4-trend-month | 261.6 | 31.9 | 8.2x | 45.1 |
| R4-trend-day | 266.4 | 33.5 | 8.0x | 45.2 |
| R4-weekday-pivot | 243.4 | 29.6 | 8.2x | 40.7 |
| R4-busiest-days | 1546.6 | 62.1 | 24.9x | 216.4 |
| **Sum of medians** | **20,625** | **2,066** | **~10x** | **4,308** |

The two R1 categories finish in under 1 ms. At that size the client round trip dominates, so the ratio
is not meaningful. The result is what matters: a 936-row summary replaces a 2M-row fact scan.

**R1 against the less-slow baseline.** Against `baseline-r2`, R1-product-all is 3.9x (1,182.8 ->
303.4 ms) and R1-product-toys 3.6x (341.8 -> 94.0 ms). These gains are larger than the 15% run-to-run
noise and the drift between baselines, so they can be claimed.

**Caveat for every ratio.** Baseline drift between sessions reaches about 37% for single cases, and
the total moved 25% on a re-run. Treat ratios under about 1.3x as noise and the R1, R2 and R4 gains
above 3x as real.

## Round 1: strategies alone (label `preagg`, `config`, `indexes`, `optimized`)

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

Round 1 used the original queries for R1, R2 and R4 (R3 and R4-busiest-days were rewritten in
`optimized`). It showed that pre-aggregation (C) gives the main win and that indexes (A) and config (B)
alone are small.

## Round 2: R2 and R4 on `AGG_RIDER_DAY` (label `optimized-v2`)

`AGG_RIDER_DAY` (date x rider x order size, 145,825 rows) already holds `orders` and `units`, so the
R2 and R4 reports read it instead of the 1M-row `FACT_ORDERDELIVERY`. No new table or index was added.
`count(*)` became `sum(orders)` and `sum(totalQuantity)` became `sum(units)`; `count(DISTINCT riderKey)`
is unchanged because `riderKey` is a grain column.

| Case | baseline-r4 | optimized (round 1) | optimized-v2 |
|---|---:|---:|---:|
| R2-cube-all | 1250.5 | 943.1 | 100.8 (**12.4x**) |
| R2-pivot-orders | 730.8 | 575.0 | 65.5 (**11.2x**) |
| R2-pivot-per-rider-q1 | 226.6 | 220.3 | 27.0 (**8.4x**) |
| R2-rider-top20 | 293.2 | 297.8 | 35.7 (**8.2x**) |
| R4-rollup-all | 259.2 | 255.1 | 31.3 (**8.3x**) |
| R4-trend-month | 261.6 | 249.1 | 32.9 (**8.0x**) |
| R4-trend-day | 266.4 | 249.2 | 33.4 (**8.0x**) |
| R4-weekday-pivot | 243.4 | 242.2 | 30.3 (**8.0x**) |

Sum of medians: 20,625 -> 7,023 -> **4,210 ms (4.9x)**. Verification: `compare_runs.py` md5 equal on
all 18 cases, and `check_equivalence.py` covered the R2 and R4 rewrites on 1,000 combinations (0
mismatches). The `optimized-v2` timings were taken with A + B + C in place. Strategies A and B were
not measured separately for these rewrites; the speedup is attributed to C because the plans no
longer touch `FACT_ORDERDELIVERY`.

## Round 3: R1 on two views (label `optimized-v3`)

R1 had been left on the original queries, which cost 884 ms (category) and 1,421 ms (product).
Two summary views now serve it:

- `AGG_CATEGORY_PERIOD`: category x year x quarter x month x vehicle x size group. 936 rows, 136 kB.
- `AGG_PRODUCT_PERIOD`: the same plus product name. 755,042 rows, 76 MB.

Every R1 filter (year, quarter, month, vehicle, size group, category) is a column of these views, so
the rewrites keep the original parameters and output. In `baseline-r4/plans/R1-product-all.txt` the
plan scans `FACT_ORDERITEM` (1,999,824 rows) and joins four dimensions. In
`optimized-v3/plans/R1-product-all.txt` it reads `AGG_PRODUCT_PERIOD` once (755,042 rows) and the sort
fits in memory (`quicksort`, 1 MB).

**Why R1-product stays at about 300 ms.** The product summary is still large (76 MB), so the
remaining cost is scanning and grouping 755k rows. Making it smaller would mean dropping a grain
column, and the product drill-down needs product name. This is the one R1 case where the summary is
not tiny, and it is reported as is.

Sum over 18 cases: 2,066 ms (`optimized-v3`) vs 4,308 ms with default settings
(`optimized-v3-defaultcfg`).

## Config attribution (B), corrected

The first-round text said config had "modest" effects and that the R3-customer-top20 regression was
unexplained. Both were wrong for the final queries. The ablation below is on the final state.

| Case | jit-off only | work_mem-only | both (recheck) | final, both (`optimized-v3`) |
|---|---:|---:|---:|---:|
| R1-product-all | 1,334.2 | 333.7 | 372.7 | 303.4 |
| R1-product-toys | 201.4 | 103.2 | 124.9 | 94.0 |
| R2-cube-all | 178.6 | 123.8 | 132.7 | 99.6 |
| R3-deciles-all | 300.9 | 240.2 | 249.2 | 212.1 |
| R3-geo-country | 626.8 | 468.8 | 464.0 | 405.7 |
| R3-customer-top20 | 734.3 | 574.0 | 572.8 | 505.6 |
| R4-busiest-days | 200.4 | 179.1 | 175.0 | 62.1 |
| **Sum of medians (18 cases)** | **4,091.7** | **2,492.7** | **2,578.0** | **2,066.3** |

- **`work_mem = 64MB` is the effective setting.** It removes the disk sorts. On R1-product-all with
  `jit` off but `work_mem` at 4 MB, the 44 MB external sort in `optimized-v3-defaultcfg` takes
  1,334 ms; with `work_mem` 64 MB it takes 334 ms.
- **`jit = off` is close to neutral here.** It adds little on top of `work_mem`. JIT compilation is
  visible in the plans (for example about 194 ms in the isolated R3-customer-top20 plan) but it
  does not move the wall-clock result much on the rewritten queries.
- **Config still matters after the rewrite.** Default settings give 4,308 ms vs 2,066 ms (about 2.1x).

**R3-customer-top20 regression (isolated).** Round 1 measured it at 2,669 -> 3,682 ms under `config`.
I isolated it on the original query, with and without the five indexes:

| Config | With indexes (ms) | Without indexes (ms) |
|---|---:|---:|
| default (`jit` on, `work_mem` 4 MB) | 2,804 | 2,689 |
| `jit = off` only | 2,450 | 2,718 |
| `work_mem = 64MB` only | 4,495 | 4,066 |
| both | 4,667 | 4,123 |

Mechanism, from the isolated plans (`evidence/benchmark/iso-default/plans/` and
`iso-workmem-only/plans/`): at 4 MB the planner chooses a **parallel plan** (`Gather Merge`, 2 workers)
whose worker sorts go to disk, which is slower but uses all cores. At 64 MB the sorts fit in memory,
so the planner picks a **serial** plan (no `Gather Merge`, in-memory `quicksort`), and that is
slower on this query. The regression is therefore a planner choice, not a bad sort. Indexes make no
difference (2,804 vs 2,689 ms). `jit` makes no clear difference either: the 2,450 vs 2,804 gap is
within the noise.

On the rewritten query the regression does not appear. R3-customer-top20 reads `AGG_CUSTOMER_PERIOD`
and `work_mem` helps it (812 -> 506 ms).

## Index findings (strategy A)

- **Helped (original queries):** R3-geo-city 72.6 -> 31.1 ms (2.3x; plan: `Index Scan using
  ix_item_geo` instead of a fact scan), R4-busiest-days 1,547 -> 1,025 ms (1.5x; `Index Scan using
  ix_delivery_deliverydate`, 365 loops).
- **Did not help:** every unfiltered or wide report. For example R1-category-all reads all 2M
  order lines (`Seq Scan on FACT_ORDERITEM`, rows=1,999,824). An index cannot beat a full scan when
  the query needs every row.
- **Not useful, dropped:** four more indexes on rider and order size were built, measured at
  `idx_scan = 0` over all 18 cases, and dropped (`evidence/benchmark/indexes/index-usage.txt`).
- **Kept, but unused by the final queries:** the five remaining indexes add about 63 MB (15 + 15 +
  13 + 13 + 7 MB). They serve the original-query path. If the app moves to the optimized queries,
  they can be dropped to save that space. That is a decision for the team (see below).

## Report guide questions

**Which primary indexes are available and used?** Each dimension has a surrogate primary key
(`DIM_CUSTOMER_pkey`, `DIM_GEOGRAPHY_pkey`) and a natural-key UNIQUE index. The plans use them for
point lookups. The joins to the small dimensions (`DIM_RIDER` 101 rows, `DIM_ORDERSIZE` 5 rows) are
sequential scans, because scanning a few hundred rows is cheaper than an index lookup per row.

**Which secondary indexes were added, and what did they do?** Five B-tree indexes on fact foreign
keys (`ix_item_deliverydate`, `ix_item_customer`, `ix_item_product`, `ix_item_geo`,
`ix_delivery_deliverydate`). They helped two of the original queries (above). On the final
rewritten queries none is used.

**Should every column be indexed? Give an instance where an index does not help.** No. Four
candidate indexes showed no use in any of the 18 cases and were dropped. The clearest case is
R1-category-all: the report aggregates every order line, so the planner scans the whole fact table
whatever the index. Indexes help only when a filter is selective. The original R1 queries had
almost no such filter, which is why the summary tables helped more than indexes did.

**Does restructuring with joins help?** Yes. Each pre-aggregated view does the fact-to-dimension joins
once. In the original R1-product-all plan the query joins four dimensions per run (about 2M rows of
join input). In the final plan it reads one 755k-row table and does no joins. For R3, the original
`count(DISTINCT orderNumber)` required a sort per group over 2M rows. The view computes it once at
customer x geography x period grain. The rewrite is exact because each order has one customer,
geography and delivery date (0 violations checked), so `sum(orders)` on the view equals the
distinct count on the fact.

**Hardware-level optimization.** Memory is the lever that mattered: `work_mem` decides whether sorts
spill to disk (for example 95 MB and 119 MB of external sort on R3-geo-country and
R3-customer-top20 in the baseline), and it also decides whether the planner uses parallel workers.
JIT compilation cost is visible in the plans but is not a large wall-clock factor here. We did not
change `shared_buffers` (128 MB, default; the 531 MB database does not fit) or the worker count, so
those are untested. The Docker VM has 7.6 GB RAM and 16 CPUs; the host has a 512 GB NVMe SSD.

**Impact of the query operations.** The expensive operators are `count(DISTINCT ...)` (a sort per
group), `CUBE` and `GROUPING SETS` (one aggregation per grouping set over the full fact), and
window functions on large inputs. Once the input is a summary of a few hundred thousand rows or
fewer, the same operators finish in 25-100 ms (R2 and R4 after round 2). The remaining cost is the
number of grouping sets times the rows per set.

## Costs and risks

- **Freshness.** The views are snapshots. After every ETL load run `db/scripts/apply_optimizations.sh`
  (or `REFRESH MATERIALIZED VIEW` on the four `AGG_*` views). Build times: about 9.5 s for the
  customer view and 0.9 s for the rider view. A `--rebuild` drops the views and indexes, so re-run
  the script afterwards. `ALTER DATABASE` settings survive a rebuild.
- **Storage.** Database size 355 MB (baseline) -> 531 MB (all three strategies). The four views are
  28 + 8.7 + 0.14 + 76 MB. The five indexes added about 64 MB; they are retired (see strategy A), so
  the applied total is about 467 MB.
- **Filters not covered.** The rewrites serve the filters the reports expose. A new filter on a
  column a summary lacks needs the original query.
- **Wired into the app.** `olap/queries/` now holds the optimized queries, so `olap-backend` and CI
  read them. The unoptimized originals are kept in `evidence/benchmark/original-queries/`, and
  `check_equivalence.py` compares the two sets. The API needs the four `AGG_*` views to exist, so
  `db/scripts/apply_optimizations.sh` is a required step after every load or rebuild. Without it the
  report queries fail with "relation does not exist".

## Measurement notes

- Run-to-run noise is up to about 15% (`baseline-r2` vs `baseline-r2-check`, same state, 18/18 md5
  equal). Differences below about 1.15x are not evidence of an effect. The 0.88-0.98x entries under
  `preagg` for R2 cases are noise: those queries are unchanged in that label.
- Baseline drift between sessions reaches about 37% for single cases (`baseline-r4` is slower than
  `baseline-r2` on R1-product-toys by 37%). `baseline-r3` was the first run of the session and is
  inflated on the R1 cases (cold cache). `baseline-r4` was re-run warm in the same session as the
  strategy labels and is the reference above.
- The same final configuration re-run in a later session gave 2,578 ms instead of 2,066 ms
  (`ablate-both-recheck`), a 25% drift on the total. Ratios in this log use the same-session
  reference.
- Timings are client wall-clock around execute and fetch on the same machine as the Docker VM.
