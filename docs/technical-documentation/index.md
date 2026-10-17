# Technical Documentation Evidence Index

This index is the entry point for report-ready project evidence. Every entry
names the committed artifact, what it proves, and the work item that produced
it. Measurements are recorded when the work runs; they are not reconstructed
from memory for the final report.

## Evidence map

| Artifact | What it proves | Produced by |
|---|---|---|
| [`evidence/source-import-report.json`](../../evidence/source-import-report.json) | The official archive hash matched, all six source tables committed with exact row counts, and the imported database passed schema and orphan checks. | Source database setup |
| [`evidence/source-db-revalidation.json`](../../evidence/source-db-revalidation.json) | A later read-only validation reproduced the six table counts, schema checks, and zero-orphan result. | Source database setup |
| [`docs/technical-documentation/profiling.md`](profiling.md) | Measured source limitations, their analytical consequences, and the warehouse corrections adopted in response. | Warehouse design / ETL-4 |
| [`docs/database/data-warehouse-schema.md`](../database/data-warehouse-schema.md) | The approved star schema, grains, facts, dimensions, hierarchies, analytical questions, and report plan. | Warehouse design |
| [`db/dw/validate/warehouse_readiness.sql`](../../db/dw/validate/warehouse_readiness.sql) | The executable structural gate for nine tables, expected columns, keys, Unknown members, order-size seeds, and fact-row state. | Warehouse construction |
| [`docs/database/data-warehouse-implementation.md`](../database/data-warehouse-implementation.md) | The implemented PostgreSQL types, constraints, grains, load order, and recorded readiness verification. | Warehouse construction |
| [`evidence/etl-rejects.json`](../../evidence/etl-rejects.json) | The latest dimension and fact reject counts, reasons, samples, and pass status. | ETL-2 |
| [`evidence/etl-reconciliation.json`](../../evidence/etl-reconciliation.json) | Fifteen source-to-warehouse count, unit, Unknown-member, and reject checks from a read-only post-load reconciliation. | ETL-3 |
| [`evidence/etl-runs.jsonl`](../../evidence/etl-runs.jsonl) | One append-only record per real ETL invocation, including command, timestamps, measured timings, rows written, rejects, and exit status. | ETL-4 |
| [`etl/run_pipeline.py`](../../etl/run_pipeline.py) and [`etl/run_etl.sh`](../../etl/run_etl.sh) | The reproducible full-pipeline order, fail-fast boundaries, safe empty-warehouse default, and explicit warehouse-only rebuild entry point. | ETL organization refactor |
| [`olap/queries/README.md`](../../olap/queries/README.md) | Four parameterized reports (12 level files) covering all five OLAP operations, with their parameters, measures and advanced SQL. | OLAP queries |
| [`evidence/benchmark/README.md`](../../evidence/benchmark/README.md) | An 18-case read-only baseline (median of 5 runs), the `EXPLAIN (ANALYZE, BUFFERS)` plans, the bottlenecks they expose, and the measured generic-plan hazard. | Performance baseline |
| [`olap-backend/`](../../olap-backend/) | The Go API (`net/http` + `pgx/v5`) that runs the report SQL read-only and serves validated JSON, plus [`olap-backend/README.md`](../../olap-backend/README.md). | OLAP application |
| [`olap-frontend/`](../../olap-frontend/) | The React dashboard: R1–R2 implemented with filters, drill-down and CSV export; R3–R4 placeholder. | OLAP application |
| [`docs/technical-documentation/application-architecture.md`](application-architecture.md) | Component map, request flow, and the safety and plan-cache decisions behind the API. | OLAP application |
| [`docs/project-checklist.md`](../project-checklist.md) | Repository-backed completion status across the full MCO1 methodology. | Project tracking |

Still pending: functional-test evidence for the reports and the
post-optimization performance comparison (Step 6).

## Evidence convention for future work

Every OLAP-query, dashboard, functional-testing, performance-testing, and
optimization ticket must commit or link a reproducible evidence artifact. At
minimum, that artifact must identify:

1. the exact command, query, test, or application action;
2. the UTC start and finish time plus measured wall-clock duration;
3. the parameters, filters, dataset/database state, and relevant row counts;
4. rejected, quarantined, or errored records, including a zero count;
5. success/failure status and enough detail to reproduce the result; and
6. the implementation ticket or pull request that generated it.

Measured values must come from an actual execution. Estimates and handwritten
fixtures cannot be presented as execution evidence. JSON is appropriate for a
single structured report; JSONL is used for an append-only sequence of runs.

## ETL run-ledger interpretation

- `rowsWritten` means rows inserted or updated by that invocation. Dimension
  rows that were unchanged are not counted as writes.
- Fact loads use their committed reload counts.
- `--check` and `--reconcile` are read-only, so their `tables` object is empty;
  their total measured time is still recorded.
- The current pipeline has no quarantine path, so `quarantinedRows` is zero.
  Invalid dimension or fact rows are rejected and abort the transaction.
- Both successful and failed invocations are retained. A nonzero `exitStatus`
  must not be removed from the ledger.

## ETL operator workflow

`bash etl/run_etl.sh` runs the complete date, dimension, fact,
reconciliation, and final-check sequence only when the warehouse has no fact
rows. `bash etl/run_etl.sh --rebuild` is the explicit full-refresh path and
recreates only the warehouse schema. The direct cross-platform entry point is
`uv run --project etl python etl/run_pipeline.py`; its rebuild option requires
Bash. These commands never reset or write to `source_db`.

