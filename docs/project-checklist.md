# Project Checklist — Data Warehouse OLAP Dashboard

> Status as of 2026-10-18. Checked items have repository evidence; unchecked items are scaffold-only (`.gitkeep`) or empty.

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
  - Evidence: Python via `uv` (`etl/pyproject.toml`, psycopg + pytest); CI runs the suites on every relevant push (`.github/workflows/pipeline-tests.yml` for the ETL and importer tests, `api-tests.yml` for the Go API, `dashboard-build.yml` for the dashboard build).
- [x] Write code to **Extract** data from the source database.
  - Evidence: read-only source queries are centralized in `etl/extract/queries.py`; `etl/load/date.py`, `etl/load/dimensions.py`, and `etl/load/facts.py` stream all six source tables through server-side cursors (10,000-row batches; no full-table reads).
- [x] Write code to **Transform** the data (wrangle, clean, split, merge, aggregate, fix null values, correct data types).
  - Evidence: `etl/transform/dates.py`, `etl/transform/values.py`, and the three `etl/load/` modules: two date formats parsed to `DATE`; gender M/F/Male/Female → M/F; vehicles 6 → 4; categories 14 → 9; prices `REAL` → `NUMERIC(12,2)` (920 rounded, catalog total +₱0.42); names merged; orders aggregated (total units, line items, size band); rider-day snapshot built with zero-order days. Every source issue and decision: `docs/database/source-schema.md` (issues 1–9), `docs/database/design-decisions.md`.
- [x] Write code to **Load** the transformed data into the data warehouse.
  - Evidence: `etl/load/date.py`, `etl/load/dimensions.py`, and `etl/load/facts.py` are invoked by the stable `etl/main.py --date` / `--dims` / `--facts` modes: 365 dates; 100 / 100,000 / 100,000 / 10,000 dimension rows; 1,000,000 / 1,999,824 / 36,500 fact rows; 0 rejects (`evidence/etl-rejects.json`); full rebuild ~40 s; reruns byte-identical. `etl/main.py --reconcile` produced `evidence/etl-reconciliation.json`: 15/15 source-to-warehouse checks passed, including 10,999,917 units in all three facts, exact Unknown seed rows, and 0 fact references to Unknown members.
- [x] Provide a reproducible, fail-fast full-pipeline command.
  - Evidence: `etl/run_pipeline.py` orchestrates date → dimensions → facts → reconciliation → final readiness check; `etl/run_etl.sh` is a thin Bash wrapper. The default refuses a populated warehouse before any load, while explicit `--rebuild` recreates only `dw_db`; runner and wrapper safety is covered by `etl/tests/test_run_pipeline.py`.

## 4. OLAP Application Development

- [x] Formulate complex queries utilizing OLAP operations (roll-up, drill-down, slice, dice, pivot).
  - Evidence: `olap/queries/` holds the four reports (12 parameterized level files) documented in `olap/queries/README.md`; all five OLAP operations are covered (`ROLLUP`, `CUBE`, `GROUPING SETS`, pivot via `FILTER`, window functions). They realize the 22 business questions in `docs/database/data-warehouse-schema.md` and are benchmarked in `evidence/benchmark/`. Every filter is a bound parameter (`:'name'`), never concatenated SQL.
- [x] Develop a web-based dashboard application.
  - Evidence: Go API in `olap-backend/` (`net/http` + `pgx/v5`, read-only pool, `force_custom_plan`; 11 tests via `go test ./...`) and React dashboard in `olap-frontend/` (Vite, no UI libraries) covering all four reports: R1 (Products & Categories), R2 (Fleet & Rider Workload), R3 (Customer Value) and R4 (Demand Calendar).
- [x] Implement UI features allowing users to specify query parameters and filters (for slice and dice).
  - Evidence: `olap-frontend/src/components/FilterBar.jsx` with `src/lib/dimensions.js` drives the per-report filter sets — year/quarter/month/vehicle/order size for R1, those plus courier and rider age for R2, year/quarter/customer gender for R3, and period/day type (weekday or weekend)/payday/vehicle/order size for R4 — all exposed by the API (see `olap-frontend/README.md`). Each report sends an endpoint only the filters that level declares, since the API rejects an undeclared parameter.
- [x] Implement UI features allowing users to view reports at varying levels of granularity (for drill-down and roll-up).
  - Evidence: `olap-frontend/src/components/RoutePath.jsx` renders the drill path and rolls back up; R1 drills Category → Product, R2 drills Couriers → Vehicles → Riders, R3 offers peer views (Deciles / Geography / Customers) whose drill state — decile, country, city — the route line rolls back, and R4 rolls the whole date hierarchy up in one table (month, its quarter, its year, the grand total) and opens any period at the next finer grain, down to the day-grain demand calendar.

## 5. Functional Testing

- [ ] Prepare functional test scripts designed for efficient testing.
  - State: current coverage is the unit/contract suites (`go test ./...` in `olap-backend`, `uv run --project etl pytest etl/tests`, `uv run --project db pytest db/source/importer`) plus the dashboard's mock/live modes; a standalone functional-test script for the reports is still pending.
- [ ] Execute each query multiple times using different parameter values.
  - State: `olap/benchmark/run_benchmark.py` already runs all 18 report cases with varied filters; a dedicated correctness pass over parameter combinations is still pending.
- [ ] Verify that the resulting reports and analytical data are correct.
  - ETL input baseline: `evidence/etl-reconciliation.json` fixes the official warehouse totals that future report tests must reconcile against (1,000,000 deliveries; 1,999,824 order items; 36,500 rider-days; 10,999,917 units).

## 6. Performance Testing & Optimization

- [x] Run each query multiple times (varying parameters, structure, or setup) and record baseline execution times.
  - Evidence: `olap/benchmark/run_benchmark.py` ran the 18 cases (1 warm-up + 5 measured runs each) into `evidence/benchmark/baseline/`; a second folder `evidence/benchmark/baseline-generic-plan/` records the same cases under `force_generic_plan`.

  | Baseline input | Current value | Evidence |
  |---|---:|---|
  | Loaded delivery facts | 1,000,000 rows | `evidence/etl-reconciliation.json` |
  | Loaded order-item facts | 1,999,824 rows | `evidence/etl-reconciliation.json` |
  | Loaded rider-day facts | 36,500 rows | `evidence/etl-reconciliation.json` |
  | Full ETL rebuild | ~40 seconds | `docs/database/data-warehouse-implementation.md` |
  | OLAP query timings before optimization | 18 cases, medians 66–8,224 ms | `evidence/benchmark/baseline/results.csv` |
  | OLAP query timings after optimization | Pending | To be captured after applying optimizations |
- [x] Evaluate performance and identify bottlenecks using the `EXPLAIN` feature.
  - Evidence: `EXPLAIN (ANALYZE, BUFFERS)` per case in `evidence/benchmark/baseline/plans/`; bottlenecks (disk sorts, full fact scans, missing planner statistics) summarized in `evidence/benchmark/README.md`.
- [ ] Apply database optimization strategies (e.g., secondary indexes, query reformulation, denormalization).
  - State: not yet applied; the baseline's "no secondary indexes" floor and candidates are documented in `evidence/benchmark/README.md`.
- [ ] Compare execution times between the original implementation and the optimized implementation.
- [ ] Analyze and explain the causes for performance improvement (or lack thereof) to include in the final report.

## 7. Final Technical Report

- [ ] Download the prescribed Technical Report template.
- [ ] Gather all data, execution times, and analyses collected from Steps 1 through 6.
  - Evidence trail established in `docs/technical-documentation/index.md`; ETL executions are in `evidence/etl-runs.jsonl`, OLAP queries in `olap/queries/`, and the performance baseline in `evidence/benchmark/`. Functional-test and post-optimization evidence remain pending.
- [ ] Complete and finalize the Technical Report.
  - State: evidence index and consolidated profiling record exist; the prescribed report template and Sections 4–6 results remain pending.
