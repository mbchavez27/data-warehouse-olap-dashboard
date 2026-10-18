# Project Checklist — Data Warehouse OLAP Dashboard

> Status as of 2026-10-18, re-verified after PR #15 (query optimizations) and PR #16 (functional tests): every suite below was re-run and passed. Checked items have repository evidence. The final technical report is tracked separately and is not part of this checklist.

## 1. Source Database Setup

- [x] Download the source dataset.
  - Evidence: official `MCO1_dataset_ecommerce.zip` present locally (gitignored) + extracted `db/raw-dumps/faker_{Couriers,Riders,Users,Products,Orders,OrderItems}.sql`; `evidence/source-import-report.json: archive.file = MCO1_dataset_ecommerce.zip`, `sha256 = a10f1186...`, `hashMatches: true`.
- [x] Import the dataset into a local MySQL or Postgres database.
  - Evidence: Postgres 16 `source_db` via `docker-compose.yml` (`source_db`, port 5433); canonical DDL `db/source/init/01_source_schema.sql`; all-Python importer `db/source/importer/` (`cli.py`, `source_import.py`, `archive_reader.py`, `stadvdb-mco1-db` uv env, 33 pytest); one-command setup `db/scripts/setup_source.sh --archive <zip> --reset`; `evidence/source-import-report.json: import.transaction = committed`, `database.passed: true`; `evidence/source-db-revalidation.json: passed: true`. Counts: Couriers 3, Riders 100, Users 100000, Products 10000, Orders 1000000, OrderItems 1999824 (3,109,927 rows total), 0 orphans.
  - Docs: `docs/database/source-database-setup.md`, `docs/database/source-schema.md`.
- [x] *(If necessary)* Generate synthetic data to increase the size of the source database.
  - Evidence: N/A — `docs/database/source-database-setup.md` records 3,109,927 rows already sufficient; no synthetic rows added.
- [x] Second team member reproduces fresh-clone procedure (`docs/database/source-database-setup.md` acceptance list).
  - Evidence: second member ran the documented gates on this workstation (33 pytest, `verify`, `validate`, live `import --reset` + full `setup_source.sh` flow, both evidence `passed:true`). Same-machine run — separate-hardware fresh clone not performed.

## 2. Data Warehouse Construction

- [x] Design the dimensional model (Star or Snowflake schema).
  - State: `docs/database/data-warehouse-schema.md` specifies a star schema with 3 facts (`FACT_ORDERDELIVERY`, `FACT_ORDERITEM`, `FACT_RIDERDAILY`) + 6 dims + 5 hierarchies + 22 questions with OLAP ops. Canonical profiling findings and corrections: `docs/technical-documentation/profiling.md`.
- [x] Include at least one (1) fact table.
  - Evidence: 3 fact tables implemented in `db/dw/init/01_dw_schema.sql`.
- [x] Include at least three (3) dimension tables.
  - Evidence: 6 dimension tables implemented in `db/dw/init/01_dw_schema.sql`.
- [x] Incorporate dimensional hierarchies required for OLAP operations (e.g. date day→month→quarter→year, product→category, city→country, rider→courier).
  - Evidence: 5 hierarchies in `docs/database/data-warehouse-schema.md` (date, rider→courier, city→country, band group, category→product); customer hierarchy is Gender-only after the `ageBand` removal.
- [x] Implement the data warehouse schema in MySQL or Postgres.
  - Evidence: `db/dw/init/01_dw_schema.sql` (9 tables, 9 PKs, 13 enforced FKs, 5 Unknown rows + 4 order-size bands, idempotent re-runnable); verified live on `dw_db` (Postgres 16 @ `:5434`): 11/9/4/5/6/6 dim columns, 10/10/7 fact columns, 0 fact rows pre-ETL. Build record: `docs/database/data-warehouse-implementation.md`.

## 3. ETL Pipeline Setup

- [x] Select a programming language (Python, Java, etc.) for the ETL script.
  - Evidence: Python via `uv` (`etl/pyproject.toml`, psycopg + pytest); CI runs the suites on every relevant push (`.github/workflows/pipeline-tests.yml` for the ETL and importer tests, `api-tests.yml` for the Go API and the SQL-to-catalog query contract, `dashboard-tests.yml` for the dashboard's suites, `dashboard-build.yml` for the dashboard build).
- [x] Write code to **Extract** data from the source database.
  - Evidence: read-only source queries are centralized in `etl/extract/queries.py`; `etl/load/date.py`, `etl/load/dimensions.py`, and `etl/load/facts.py` stream all six source tables through server-side cursors (10,000-row batches; no full-table reads).
- [x] Write code to **Transform** the data (wrangle, clean, split, merge, aggregate, fix null values, correct data types).
  - Evidence: `etl/transform/dates.py`, `etl/transform/values.py`, and the three `etl/load/` modules: two date formats parsed to `DATE`; gender M/F/Male/Female → M/F; vehicles 6 → 4; categories 14 → 9; prices `REAL` → `NUMERIC(12,2)` (920 rounded, catalog total +₱0.42); names merged; orders aggregated (total units, line items, size band); rider-day snapshot built with zero-order days. Every source issue and decision: `docs/database/source-schema.md` (issues 1–9), `docs/database/design-decisions.md`.
- [x] Write code to **Load** the transformed data into the data warehouse.
  - Evidence: `etl/load/date.py`, `etl/load/dimensions.py`, and `etl/load/facts.py` are invoked by the stable `etl/main.py --date` / `--dims` / `--facts` modes: 365 dates; 100 / 100,000 / 100,000 / 10,000 dimension rows; 1,000,000 / 1,999,824 / 36,500 fact rows; 0 rejects (`evidence/etl-rejects.json`); full rebuild ~40 s; reruns byte-identical. `etl/main.py --reconcile` produced `evidence/etl-reconciliation.json`: 15/15 source-to-warehouse checks passed, including 10,999,917 units in all three facts, exact Unknown seed rows, and 0 fact references to Unknown members.
- [x] Provide a reproducible, fail-fast full-pipeline command.
  - Evidence: `etl/run_pipeline.py` orchestrates date → dimensions → facts → reconciliation → summary views (`--optimize`) → final readiness check; `etl/run_etl.sh` is a thin Bash wrapper. The default refuses a populated warehouse before any load, while explicit `--rebuild` recreates only `dw_db`; runner and wrapper safety is covered by `etl/tests/test_run_pipeline.py`.

## 4. OLAP Application Development

- [x] Formulate complex queries utilizing OLAP operations (roll-up, drill-down, slice, dice, pivot).
  - Evidence: `olap/queries/` holds the four reports (12 parameterized level files) documented in `olap/queries/README.md`; all five OLAP operations are covered (`ROLLUP`, `CUBE`, `GROUPING SETS`, pivot via `FILTER`, window functions). They realize the 22 business questions in `docs/database/data-warehouse-schema.md` and are benchmarked in `evidence/benchmark/`. Every filter is a bound parameter (`:'name'`), never concatenated SQL.
- [x] Develop a web-based dashboard application.
  - Evidence: Go API in `olap-backend/` (`net/http` + `pgx/v5`, read-only pool, `force_custom_plan`; 11 tests via `go test ./...`) and React dashboard in `olap-frontend/` (Vite, no UI libraries) covering all four reports: R1 (Products & Categories), R2 (Fleet & Rider Workload), R3 (Customer Value) and R4 (Demand Calendar). The dashboard reads the reports with charts sized to the data (Pareto with an 80% line, trend line, rider dot strip, demand calendar, heat grids with "against its average" colourings), sortable tables, column explanations, keyboard and touch reading of the charts, and a light/dark switch; `olap-frontend/README.md` describes each.
- [x] Implement UI features allowing users to specify query parameters and filters (for slice and dice).
  - Evidence: `olap-frontend/src/components/FilterBar.jsx` with `src/lib/dimensions.js` drives the per-report filter sets — year/quarter/month/vehicle/order size for R1, those plus courier and rider age for R2, year/quarter/customer gender for R3, and period/day type (weekday or weekend)/payday/vehicle/order size for R4 — all exposed by the API (see `olap-frontend/README.md`). Each report sends an endpoint only the filters that level declares, since the API rejects an undeclared parameter.
- [x] Implement UI features allowing users to view reports at varying levels of granularity (for drill-down and roll-up).
  - Evidence: `olap-frontend/src/components/RoutePath.jsx` renders the drill path and rolls back up; R1 drills Category → Product, R2 drills Couriers → Vehicles → Riders, R3 offers peer views (Deciles / Geography / Customers) whose drill state — decile, country, city — the route line rolls back, and R4 rolls the whole date hierarchy up in one table (month, its quarter, its year, the grand total) and opens any period at the next finer grain, down to the day-grain demand calendar.

## 5. Functional Testing

- [x] Prepare functional test scripts designed for efficient testing.
  - Evidence: `olap/tests/` (74 tests in three modules, about 90 s, run by `uv run --project etl python -m unittest discover -s olap/tests -v`; documented in `olap/tests/README.md`). `test_api_contract.py` covers the live API's contract (17 tests), `test_warehouse_integrity.py` checks `dw_db` against `source_db` and the `AGG_*` views (20), and `test_report_correctness.py` compares every report level with an independent reference (37). Runs are in `evidence/functional-tests/results.txt` (twice, both OK), `results-after-rebase.txt` (after the rebase onto `main`, OK), and `negative-control.txt` (dropping one source order fails 29 subtests across 10 tests; `FAILED (failures=29)`). The suite is read-only. It is not run in CI because it needs the loaded `dw_db` and `source_db` (1M orders, gitignored dataset), so it runs locally.
  - Unit and contract suites already in CI: `.github/workflows/pipeline-tests.yml` (ETL, importer), `api-tests.yml` (Go API, query contract), `dashboard-tests.yml` (dashboard, 407 checks: the column contract for all 12 levels, all four reports rendered server-side across their views and drill levels, the table sort, the chart keyboard and pointer handling, and the theme's contrast and dark tokens), `dashboard-build.yml`.
- [x] Execute each query multiple times using different parameter values.
  - Evidence: `olap/tests/test_report_correctness.py` sends 131 distinct report requests to the live API (count in `evidence/functional-tests/report-request-count.txt`), and each is checked against the reference (`evidence/functional-tests/results.txt`). `olap/benchmark/run_benchmark.py` times the 18 cases over varied filters (1 warm-up + 5 runs each; `evidence/benchmark/`).
- [x] Verify that the resulting reports and analytical data are correct.
  - Evidence: the report values are checked against `source_db` in `test_report_correctness.py`, and the warehouse totals are checked in `test_warehouse_integrity.py` (1,000,000 deliveries, 1,999,824 order items, 10,999,917 units). The totals also match `evidence/etl-reconciliation.json`. `evidence/contract-check.json` records the dashboard-to-warehouse column agreement.

## 6. Performance Testing & Optimization

- [x] Run each query multiple times (varying parameters, structure, or setup) and record baseline execution times.
  - Evidence: `olap/benchmark/run_benchmark.py` ran the 18 cases into `evidence/benchmark/baseline/` (1 warm-up + 5 measured runs) and, for the final comparison, `evidence/benchmark/baseline-r4/` (1 warm-up + 9 timed runs, median); `evidence/benchmark/baseline-generic-plan/` records the same cases under `force_generic_plan`.

  | Baseline input | Current value | Evidence |
  |---|---:|---|
  | Loaded delivery facts | 1,000,000 rows | `evidence/etl-reconciliation.json` |
  | Loaded order-item facts | 1,999,824 rows | `evidence/etl-reconciliation.json` |
  | Loaded rider-day facts | 36,500 rows | `evidence/etl-reconciliation.json` |
  | Full ETL rebuild | ~40 seconds | `docs/database/data-warehouse-implementation.md` |
  | OLAP query timings before optimization | 18 cases, medians 66–8,224 ms | `evidence/benchmark/baseline/results.csv` |
  | OLAP query timings after optimization | 18 cases, sum of medians 2,066 ms vs 20,625 ms (about 10x; 8–10x as the honest range) | `evidence/benchmark/optimized-v3/results.csv`, `evidence/optimization-log.md` |
- [x] Evaluate performance and identify bottlenecks using the `EXPLAIN` feature.
  - Evidence: `EXPLAIN (ANALYZE, BUFFERS)` per case in `evidence/benchmark/baseline/plans/`; bottlenecks (disk sorts, full fact scans, missing planner statistics) summarized in `evidence/benchmark/README.md`.
- [x] Apply database optimization strategies (e.g., secondary indexes, query reformulation, denormalization).
  - Evidence: strategy C (four materialized summary views, `AGG_CATEGORY_PERIOD`, `AGG_PRODUCT_PERIOD`, `AGG_RIDER_DAY`, `AGG_CUSTOMER_PERIOD`, in `db/dw/optimize/03_preagg.sql`) with query rewrites in `olap/queries/`; strategy B (`jit=off`, `work_mem=64MB`, `db/dw/optimize/02_config.sql`); strategy A (five indexes) was tested and retired because no final plan uses it (`db/dw/optimize/01_indexes.sql`). Applied by the ETL pipeline after every load (`etl/main.py --optimize`, `etl/load/summaries.py`, one transaction checked against the facts), or by hand with `db/scripts/apply_optimizations.sh`.
- [x] Compare execution times between the original implementation and the optimized implementation.
  - Evidence: `evidence/benchmark/baseline-r4/` vs `evidence/benchmark/optimized-v3/`; `compare_runs.py` reports 0 md5 mismatches on the 18 cases, so results are identical. Round-by-round table in `evidence/optimization-log.md`.
- [x] Analyze and explain the causes for performance improvement (or lack thereof) to include in the final report.
  - Evidence: `evidence/optimization-log.md` (the summary views replace 2M-row fact scans; the config changes help only through `work_mem`, which avoids disk sorts; the five indexes are not used by any final plan). `evidence/benchmark/README.md` records the generic-plan hazard (up to 105x slower) and the fix (`force_custom_plan` in `olap-backend/main.go`).
