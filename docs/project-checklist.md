# Project Checklist — Data Warehouse OLAP Dashboard

> Status as of 2026-10-10. Checked items have repository evidence; unchecked items are scaffold-only (`.gitkeep`) or empty.

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
  - State: `docs/database/data-warehouse-schema.md` specifies a star schema with 3 facts (`FACT_ORDERDELIVERY`, `FACT_ORDERITEM`, `FACT_RIDERDAILY`) + 6 dims + 5 hierarchies + 22 questions with OLAP ops. Four profiling corrections applied in DDL (Q20/21 flat-geography note, Q22 concentration-only, Q14 payday rule, customer `ageBand` removal, idle-day grain note).
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
  - Evidence: Python via `uv` — proven by the `stadvdb-mco1-db` importer env; ETL follows the same stack (`stadvdb-mco1-etl` convention specced, `etl/` implementation pending).
- [ ] Write code to **Extract** data from the source database.
- [ ] Write code to **Transform** the data (wrangle, clean, split, merge, aggregate, fix null values, correct data types).
  - Known issues queued in `docs/database/source-schema.md` (mixed date formats, gender codes, float price, MySQL escapes, bulk timestamps, undeclared FKs), plus 4 profiling findings (constant `createdAt` kills lead time/benchmark/time-dim, single-age customers, uniform geography, flat demand).
- [ ] Write code to **Load** the transformed data into the data warehouse.

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

## 6. Performance Testing & Optimization

- [ ] Run each query multiple times (varying parameters, structure, or setup) and record baseline execution times.
  - State: planned `tests/perf_test.py` not present.
- [ ] Evaluate performance and identify bottlenecks using the `EXPLAIN` feature.
- [ ] Apply database optimization strategies (e.g., secondary indexes, query reformulation, denormalization).
  - State: planned `db/03_indexes.sql` not present.
- [ ] Compare execution times between the original implementation and the optimized implementation.
- [ ] Analyze and explain the causes for performance improvement (or lack thereof) to include in the final report.

## 7. Final Technical Report

- [ ] Download the prescribed Technical Report template.
- [ ] Gather all data, execution times, and analyses collected from Steps 1 through 6.
- [ ] Complete and finalize the Technical Report.
  - State: `docs/technical-documentation/` is empty.
