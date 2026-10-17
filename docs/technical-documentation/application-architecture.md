# Application Architecture

This page describes how a request reaches the warehouse and what design
decisions keep it safe and reproducible. It complements
[`olap/queries/README.md`](../../olap/queries/README.md) (the queries
themselves) and [`../../olap-backend/README.md`](../../olap-backend/README.md)
(the API reference).

## Components

| Component | Location | Role |
|---|---|---|
| Source database | `source_db`, Postgres 16, `:5433` | The imported official dataset (six tables) |
| ETL pipeline | `etl/`, `db/source/importer/` | Extract, transform and load the star-schema warehouse |
| Data warehouse | `dw_db`, Postgres 16, `:5434` | 3 fact + 6 dimension tables |
| Report queries | `olap/queries/` | 12 parameterized SQL files across four reports |
| API | `olap-backend/`, Go, `:8080` | Runs the report SQL and serves JSON |
| Dashboard | `olap-frontend/`, React + Vite, `:3000` | Filters, drill-down, tables and charts |

## Request flow

```
Browser (localhost:3000)
  └─ GET /api/reports/r1/category?year=2025      (Vite dev proxy)
       └─ Go API (localhost:8080)  internal/api
            ├─ reports.Validate       parameter + cross-parameter checks
            ├─ reports.Service.Run    translate :'name' -> $n::text, bind values
            └─ pgx pool (read-only, force_custom_plan) -> dw_db:5434
                 └─ JSON { report, level, params, columns, rows, rowCount, elapsedMs }
```

In development the dashboard's Vite server proxies every `/api/...` call to the
API, so the browser never crosses an origin and no CORS setup is needed. When
the dashboard runs from another origin, the API answers CORS for the configured
`CORS_ORIGINS`.

## Design decisions

- **The SQL files are the single source of truth.** The service does not build
  SQL in Go; it loads the files in `olap/queries/` at startup. The catalog
  (`internal/reports/catalog.go`) declares each level's parameters, and
  `LoadStatements` refuses to start if a file's parameters do not match the
  catalog — so query and API cannot drift apart silently.
- **Every filter is a bound parameter.** `Translate` turns each `:'name'` into a
  positional `$n::text` placeholder; values are validated against the parameter
  kind (enum, bounded int, or bounded text) before they are bound. Nothing is
  concatenated into SQL, and an empty value always means "no filter".
- **Read-only by construction.** The connection pool sets
  `default_transaction_read_only = on`, so a report can never write to the
  warehouse, even if a query were wrong.
- **Custom plans.** The pool sets `plan_cache_mode = force_custom_plan`.
  Reusing a server-side prepared statement lets PostgreSQL choose a generic plan
  that cannot see which filters are empty and nested-loops over every fact row —
  measured at up to 105× slower in
  [`evidence/benchmark/README.md`](../../evidence/benchmark/README.md).
- **Bounded work.** Each request runs under `QUERY_TIMEOUT` (default 60s) and the
  pooled connections cap concurrency via `DW_MAX_CONNS`.
- **The Unknown members stay invisible.** Dimension lookups exclude key `0`
  (`WHERE "riderKey" <> 0`, ...), which exists only so facts stay joinable.

## OLAP operation coverage

Each report is one folder of level files; each file is one drill level that
returns a fixed column set.

| Report | Operations |
|---|---|
| R1 Product & Category Value | roll-up (`ROLLUP`), drill-down (Category → Product), slice, dice |
| R2 Fleet, Courier & Rider Workload | pivot (`FILTER`), roll-up (`CUBE`), drill-down (Couriers → Vehicles → Riders), drill-across to `FACT_RIDERDAILY`, slice, dice |
| R3 Customer Value Distribution | roll-up (`NTILE`, cumulative share), drill-down (Deciles → Country → City → Customer), slice, dice |
| R4 Demand Calendar | roll-up (`ROLLUP`), drill-down (Year → Quarter → Month → Week → Day), pivot (month × weekday), slice, dice |

All five OLAP operations are covered. See
[`olap/queries/README.md`](../../olap/queries/README.md) for the per-file
parameters, output columns and the advanced SQL each level uses.
