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
  - Evidence: `olap/tests/` (PR #16) holds 74 read-only end-to-end tests against the loaded warehouse and the live API — `test_api_contract.py` (17), `test_warehouse_integrity.py` (20), `test_report_correctness.py` (37) — with a preflight that fails fast when a container or the API is down; one command, about 50–95 s (`olap/tests/README.md`). Below them sit the unit and contract suites, all passing on re-run: `go test ./...` (11 API tests) and `go test -tags integration ./internal/reports/` (every query prepared against the schema, in CI); `uv run --project etl pytest etl/tests` (210 tests; the 19 that need a `dw_test` database run in CI, `.github/workflows/pipeline-tests.yml`); `uv run --project db pytest db/source/importer` (33); and the dashboard's `npm test` (407 checks: the column contract for all 12 levels, all four reports rendered server-side across their views and drill levels, the table sort, the chart keyboard and pointer handling, and the theme's contrast and dark tokens), run in CI by `.github/workflows/dashboard-tests.yml`.
- [x] Execute each query multiple times using different parameter values.
  - Evidence: `test_report_correctness.py` runs every report level over about 115 filter combinations; `olap/benchmark/check_equivalence.py` compared each optimized query with its original on 1,600 randomized filter combinations (0 mismatches, `evidence/optimization-log.md`); `olap/benchmark/run_benchmark.py` times 18 report cases with varied filters; `npm run check:contracts` replays all 14 requestable levels against the live API (`evidence/contract-check.json`: columns and value types match).
- [x] Verify that the resulting reports and analytical data are correct.
  - Evidence: every report level is compared with an independent reference model computed straight from the fact tables, plus pinned hand-checked figures and internal consistency (parts sum to totals, ranks, shares, subtotals); the warehouse is checked against `source_db` (row, unit and value totals, every order on the right day, rider and customer, each `AGG_*` view an exact rollup of the base facts). `evidence/functional-tests/results.txt` records 74/74 passing and `evidence/functional-tests/negative-control.txt` shows the suite failing on deliberately wrong data. Re-run on 2026-10-18: 74/74 OK. The totals reconcile to the ETL baseline in `evidence/etl-reconciliation.json` (1,000,000 deliveries; 1,999,824 order items; 36,500 rider-days; 10,999,917 units).

## 6. Performance Testing & Optimization

- [x] Run each query multiple times (varying parameters, structure, or setup) and record baseline execution times.
  - Evidence: `olap/benchmark/run_benchmark.py` ran the 18 cases into `evidence/benchmark/baseline/` (1 warm-up + 5 measured runs) and, for the final comparison, `evidence/benchmark/baseline-r4/` (1 warm-up + 9 timed runs, median); `evidence/benchmark/baseline-generic-plan/` records the same cases under `force_generic_plan`.

  | Baseline input | Current value | Evidence |
  |---|---:|---|
  | Loaded delivery facts | 1,000,000 rows | `evidence/etl-reconciliation.json` |
  | Loaded order-item facts | 1,999,824 rows | `evidence/etl-reconciliation.json` |
  | Loaded rider-day facts | 36,500 rows | `evidence/etl-reconciliation.json` |
  | Full ETL rebuild | ~40 seconds | `docs/database/data-warehouse-implementation.md` |
  | OLAP query timings before optimization | 18 cases, sum of medians 20,625 ms | `evidence/benchmark/baseline-r4/results.csv` |
  | OLAP query timings after optimization | 18 cases, sum of medians 2,066 ms (about 8–10x; a re-run of the same state gave 2,578 ms) | `evidence/benchmark/optimized-v3/results.csv`, `evidence/optimization-log.md` |
- [x] Evaluate performance and identify bottlenecks using the `EXPLAIN` feature.
  - Evidence: `EXPLAIN (ANALYZE, BUFFERS)` per case in `evidence/benchmark/<label>/plans/`; bottlenecks (disk sorts, full fact scans, missing planner statistics) summarized in `evidence/benchmark/README.md`.
- [x] Apply database optimization strategies (e.g., secondary indexes, query reformulation, denormalization).
  - Evidence: three strategies, applied by `db/scripts/apply_optimizations.sh` (PR #15): (A) B-tree indexes on fact foreign keys, tried and then retired because no final plan uses them (`db/dw/optimize/01_indexes.sql`); (B) `jit = off` and `work_mem = 64MB` on `dw_db` (`02_config.sql`); (C) four materialized summary views (`AGG_CATEGORY_PERIOD`, `AGG_PRODUCT_PERIOD`, `AGG_CUSTOMER_PERIOD`, `AGG_RIDER_DAY`) with the report queries rewritten to read them (`03_preagg.sql`, now served from `olap/queries/`). The ETL pipeline rebuilds the views after every load (`etl/main.py --optimize`, `etl/load/summaries.py`), in one transaction checked against the facts, so a fresh or rebuilt warehouse serves the reports without a manual step.
- [x] Compare execution times between the original implementation and the optimized implementation.
  - Evidence: per-case table in `evidence/optimization-log.md` (`baseline-r4` vs `optimized-v3`, plus `optimized-v3-defaultcfg`); every optimized result set matched the baseline by md5 (`olap/benchmark/compare_runs.py`, 0 mismatches).
- [x] Analyze and explain the causes for performance improvement (or lack thereof) to include in the final report.
  - Evidence: `evidence/optimization-log.md` — the summary views replace multi-million-row fact scans (the main win), a config ablation attributes strategy B to `work_mem`, the index findings explain why the indexes were retired, an isolated R3-customer-top20 regression, costs and risks (refresh after every load), and a "Report guide questions" section for the write-up.
