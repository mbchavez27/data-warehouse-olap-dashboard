# Project Checklist — Data Warehouse OLAP Dashboard

> Status as of 2026-10-11. Checked items have repository evidence; unchecked items are scaffold-only (`.gitkeep`) or empty.

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
  - Evidence: Python via `uv` (`etl/pyproject.toml`, psycopg + pytest); CI runs every test on each push (`.github/workflows/tests.yml`).
- [x] Write code to **Extract** data from the source database.
  - Evidence: read-only source queries are centralized in `etl/extract/queries.py`; `etl/load/date.py`, `etl/load/dimensions.py`, and `etl/load/facts.py` stream all six source tables through server-side cursors (10,000-row batches; no full-table reads).
- [x] Write code to **Transform** the data (wrangle, clean, split, merge, aggregate, fix null values, correct data types).
  - Evidence: `etl/transform/dates.py`, `etl/transform/values.py`, and the three `etl/load/` modules: two date formats parsed to `DATE`; gender M/F/Male/Female → M/F; vehicles 6 → 4; categories 14 → 9; prices `REAL` → `NUMERIC(12,2)` (920 rounded, catalog total +₱0.42); names merged; orders aggregated (total units, line items, size band); rider-day snapshot built with zero-order days. Every source issue and decision: `docs/database/source-schema.md` (issues 1–9), `docs/database/design-decisions.md`.
- [x] Write code to **Load** the transformed data into the data warehouse.
  - Evidence: `etl/load/date.py`, `etl/load/dimensions.py`, and `etl/load/facts.py` are invoked by the stable `etl/main.py --date` / `--dims` / `--facts` modes: 365 dates; 100 / 100,000 / 100,000 / 10,000 dimension rows; 1,000,000 / 1,999,824 / 36,500 fact rows; 0 rejects (`evidence/etl-rejects.json`); full rebuild ~40 s; reruns byte-identical. `etl/main.py --reconcile` produced `evidence/etl-reconciliation.json`: 15/15 source-to-warehouse checks passed, including 10,999,917 units in all three facts, exact Unknown seed rows, and 0 fact references to Unknown members.
- [x] Provide a reproducible, fail-fast full-pipeline command.
  - Evidence: `etl/run_pipeline.py` orchestrates date → dimensions → facts → reconciliation → final readiness check; `etl/run_etl.sh` is a thin Bash wrapper. The default refuses a populated warehouse before any load, while explicit `--rebuild` recreates only `dw_db`; runner and wrapper safety is covered by `etl/tests/test_run_pipeline.py`.

## 4. OLAP Application Development

- [ ] Formulate complex queries utilizing OLAP operations (roll-up, drill-down, slice, dice, pivot).
  - State: 22 questions with OLAP ops specified in `docs/database/data-warehouse-schema.md`; no executable SQL yet.
- [ ] Develop a web-based dashboard application.
  - State: `olap-backend/` and `olap-frontend/` contain only `.gitkeep`; `README.md` plans Go API (`:8080`) + React (`:3000`).
- [ ] Implement UI features allowing users to specify query parameters and filters (for slice and dice).
- [ ] Implement UI features allowing users to view reports at varying levels of granularity (for drill-down and roll-up).

## 5. Functional Testing

- [ ] Prepare functional test scripts designed for efficient testing.
  - State: `tests/` contains only `.gitkeep`; planned `tests/functional_test.py` not present.
- [ ] Execute each query multiple times using different parameter values.
- [ ] Verify that the resulting reports and analytical data are correct.
  - ETL input baseline: `evidence/etl-reconciliation.json` fixes the official warehouse totals that future report tests must reconcile against (1,000,000 deliveries; 1,999,824 order items; 36,500 rider-days; 10,999,917 units).

## 6. Performance Testing & Optimization

- [ ] Run each query multiple times (varying parameters, structure, or setup) and record baseline execution times.
  - State: planned `tests/perf_test.py` not present.

  | Baseline input | Current value | Evidence |
  |---|---:|---|
  | Loaded delivery facts | 1,000,000 rows | `evidence/etl-reconciliation.json` |
  | Loaded order-item facts | 1,999,824 rows | `evidence/etl-reconciliation.json` |
  | Loaded rider-day facts | 36,500 rows | `evidence/etl-reconciliation.json` |
  | Full ETL rebuild | ~40 seconds | `docs/database/data-warehouse-implementation.md` |
  | OLAP query timings before optimization | Pending | To be captured by Step 6 performance tests |
  | OLAP query timings after optimization | Pending | To be captured after applying optimizations |
- [ ] Evaluate performance and identify bottlenecks using the `EXPLAIN` feature.
- [ ] Apply database optimization strategies (e.g., secondary indexes, query reformulation, denormalization).
  - State: planned `db/03_indexes.sql` not present.
- [ ] Compare execution times between the original implementation and the optimized implementation.
- [ ] Analyze and explain the causes for performance improvement (or lack thereof) to include in the final report.

## 7. Final Technical Report

- [ ] Download the prescribed Technical Report template.
- [ ] Gather all data, execution times, and analyses collected from Steps 1 through 6.
  - Evidence trail established in `docs/technical-documentation/index.md`; ETL executions are captured in `evidence/etl-runs.jsonl`. OLAP, functional-test, and performance evidence remains pending with Sections 4–6.
- [ ] Complete and finalize the Technical Report.
  - State: evidence index and consolidated profiling record exist; the prescribed report template and Sections 4–6 results remain pending.
