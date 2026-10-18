# Data Warehousing and OLAP Dashboard

Query Processing in a Data Warehouse. Covers ETL data wrangling, dimensional modeling, and an optimized web-based OLAP interface. | In Submission for STADVDB

## Tech Stack

- **Database:** PostgreSQL 16 (source database and data warehouse) deployed via Docker Compose.
- **ETL Pipeline:** Python with `uv` for fast dependency management.
- **Backend API:** Go 1.25 with the standard-library `net/http` router and `pgx/v5` (no web framework).
- **Frontend:** React 18 with Vite, no UI, chart or icon libraries.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- [Go](https://golang.org/doc/install) 1.25+
- [Node.js](https://nodejs.org/) 18+
- [Python](https://www.python.org/downloads/) 3.10+
- [uv](https://github.com/astral-sh/uv) (Extremely fast Python package installer and resolver)

There are two lifecycles. **Once per machine** you import the dataset and load
the warehouse (Setup below); the data lives in Docker volumes and is reused from
then on. **Every session** you start the backend and frontend (Run the app) — the
warehouse is already loaded, so that is one command.

## Setup (one time per machine)

### 1. Database Initialization

The official dataset ZIP is too large for version control and is ignored by Git. Keep `MCO1_dataset_ecommerce.zip` outside the repository; do not extract or rename its contents. The importer reads the ZIP directly (expected SHA-256 `a10f1186...862`).

From the repository root (macOS/Linux, or Git Bash/WSL on Windows):

```bash
./db/scripts/setup_source.sh --archive "/absolute/path/MCO1_dataset_ecommerce.zip" --reset
```

The script creates `.env` from `.env.example` if missing (local-only, never commit it), starts `source_db` (PostgreSQL 16 @ `localhost:5433`) via `docker compose up -d --wait source_db`, then runs the importer tests, archive verification, atomic import (3,109,927 rows), and database validation. Re-running without flags (`./db/scripts/setup_source.sh`) re-checks env, container health, tests, and validation without touching data.

_Native Windows CMD/PowerShell (no bash): run the equivalent commands directly — `Copy-Item .env.example .env`, `docker compose up -d --wait source_db`, `uv run --project db pytest db/source/importer`, `uv run --project db python db/source/importer/cli.py verify --archive <zip>`, `uv run --project db python db/source/importer/cli.py import --archive <zip> --reset`, `uv run --project db python db/source/importer/cli.py validate`._

_Confirm: open `evidence/source-import-report.json` — top-level `passed` must be `true`. Full procedure and acceptance checklist: `docs/database/source-database-setup.md`._

### 2. Load the Data Warehouse (ETL Pipeline)

The Python pipeline extracts all six source tables, applies the documented
cleaning and aggregations, loads the dimensional warehouse, reconciles the
result, and records execution evidence. Install its locked dependencies once:

```bash
uv sync --project etl
```

Run the complete workflow from the repository root:

```bash
bash etl/run_etl.sh            # safe: requires an empty/pre-load warehouse
bash etl/run_etl.sh --rebuild  # explicit: recreates only dw_db, then loads it
```

The parameterless command is deliberately non-destructive. It starts
`source_db` and `dw_db`, verifies the exact source counts, and refuses to run
the first load when warehouse facts already exist. `--rebuild` is the only
full-pipeline option that replaces the warehouse schema; it delegates to
`db/scripts/setup_dw.sh --schema-only`. Neither command resets or writes to
the source database.

The equivalent direct Python commands are:

```powershell
uv run --project etl python etl/run_pipeline.py
uv run --project etl python etl/run_pipeline.py --rebuild
```

The default direct command works in PowerShell, CMD, macOS, and Linux.
`--rebuild` requires Bash because the intentional reset uses the existing
warehouse safety script. On Windows the runner uses Git Bash, even when you
start it from PowerShell or CMD: it skips `C:\Windows\System32\bash.exe`,
which launches WSL, where this checkout's `uv` environment is not available.
Set `ETL_BASH` to a specific `bash.exe` to override.

For diagnostics or an individual phase, the stable entry points remain:

```powershell
uv run --project etl python etl/main.py --check
uv run --project etl python etl/main.py --date
uv run --project etl python etl/main.py --dims
uv run --project etl python etl/main.py --facts
uv run --project etl python etl/main.py --reconcile
uv run --project etl python etl/main.py --reconcile --output evidence/etl-reconciliation.json
```

Implementation is organized by responsibility under `etl/core/`,
`etl/extract/`, `etl/transform/`, `etl/load/`, and `etl/validate/`.

## Run the app (every session)

### Docker (one command)

The fastest way to run the API and dashboard together. This starts the Go API,
the React dev server, and the warehouse they read from:

```bash
docker compose --profile app up -d        # dashboard on :3000, API on :8080
docker compose --profile app logs -f api web
docker compose --profile app down
```

- Plain `docker compose up -d` starts only the databases. To start just the app
  stack, use `docker compose --profile app up -d api web`.
- The warehouse data persists in the `pg_source_data` / `pg_dw_data` volumes.
  `down` keeps them; `down -v` deletes them, after which you redo Setup.
- The first run is slower (Go module download, `npm install`); the
  `go_mod_cache` and `web_node_modules` volumes keep later runs fast.
- The dashboard runs in live mode against the API, so no CORS setup is needed.
- Stop any local `go run .` or `npm run dev` first — they hold the same ports.

### Local dev servers (no Docker)

To iterate with your own toolchain, run the two servers directly. The Go service
runs the parameterized OLAP report queries from `olap/queries` against the
warehouse and serves them as JSON; it opens the warehouse read-only with
`plan_cache_mode = force_custom_plan` so a reused prepared statement cannot fall
back to a bad generic plan.

```bash
cd olap-backend
go run .
```

Configuration is read from the repository-root `.env` (or `olap-backend/.env`):
`DW_HOST`, `DW_PORT`, `DW_DB`, `DW_USER`, `DW_PASSWORD`, `API_PORT`,
`QUERY_TIMEOUT`, `DW_MAX_CONNS`, `CORS_ORIGINS`, `OLAP_QUERIES_DIR`. Defaults
target the Compose warehouse at `localhost:5434/dw_db`.

```bash
cd olap-frontend
npm install
npm run dev
```

The API is available at `http://localhost:8080` (`GET /api/health` reports
warehouse reachability; `GET /api/reports` lists every report and level; run its
tests with `go test ./...`). The dashboard is at `http://localhost:3000`.

The dashboard renders built-in sample data (`src/api/mock.js`) until it is
pointed at the API, so it runs before the API is up. To load real warehouse
results, create `olap-frontend/.env.local` with `VITE_API_MODE=live` and restart;
Vite proxies every `/api/...` call to `http://localhost:8080` (`API_TARGET`
overrides that), so no CORS setup is needed in development.

All four reports are implemented, each with filters, drill-down and CSV export:

- **R1 Products & Categories** — the 9 categories, each drilled into its
  products, sliced by period and diced by vehicle and order size.
- **R2 Fleet & Rider Workload** — couriers → vehicles → riders, with a
  courier × vehicle grid (total orders or orders per rider) that jumps
  straight into the riders behind a cell.
- **R3 Customer Value** — deciles, geography and top customers as peer views.
- **R4 Demand Calendar** — the whole date hierarchy rolled up in one table,
  the trend at any grain, a month × weekday heat map, and the busiest days
  down to a daily demand calendar.

`olap-frontend/README.md` lists each report's views, filters and marks in
detail, and the endpoints each one calls.

## Documentation

| Document | Covers |
|---|---|
| `docs/database/source-database-setup.md` | Source import procedure and acceptance checks |
| `docs/database/source-schema.md` | Source schema and wrangling issues |
| `docs/database/data-warehouse-schema.md` | Star schema, hierarchies, business questions, reports |
| `docs/database/data-warehouse-implementation.md` | Implemented warehouse types, constraints and load order |
| `olap/queries/README.md` | The four OLAP reports, their parameters and measures |
| `olap-frontend/README.md` | Dashboard layout and the API contract it expects |
| `olap-backend/README.md` | API configuration, endpoints and read-only guarantees |
| `evidence/benchmark/README.md` | Query baseline, plan bottlenecks and the generic-plan hazard |
| `docs/project-checklist.md` | Repository-backed completion status for every methodology step |
| `docs/technical-documentation/index.md` | Evidence index for the final report |

## Testing and Optimization (Steps 5 & 6)

Test suites: `uv run --project etl pytest etl/tests` (ETL),
`uv run --project db pytest db/source/importer` (source importer), and
`go test ./...` in `olap-backend` (API). CI runs the suite for each area on the
paths it covers — `.github/workflows/pipeline-tests.yml` (ETL and importer),
`api-tests.yml` (the API, plus every report query prepared against the warehouse
schema) and `dashboard-tests.yml` (the dashboard's own suites) — and builds the
dashboard (`.github/workflows/dashboard-build.yml`).

The dashboard has its own suite. `npm test` in `olap-frontend` holds the sample
data to a generated column contract for all 12 report levels and renders the
four reports server-side in every view state (233 checks, no database, run in
CI by `.github/workflows/dashboard-tests.yml`); `npm run check:contracts` diffs
that contract, and the value types of the sample data, against the live API and
writes `evidence/contract-check.json`. The SQL-to-catalog link is checked from
the Go side too: `go test -tags integration ./internal/reports/` prepares every
query against the warehouse schema in CI (`.github/workflows/api-tests.yml`).
All of it is structural: report-level end-to-end checks that reconcile the
analytical results to the ETL baseline are still to be added.

Performance baseline: `olap/benchmark/run_benchmark.py` runs the 18 report cases
(1 warm-up plus 5 measured runs each) and writes timings and
`EXPLAIN (ANALYZE, BUFFERS)` plans under `evidence/benchmark/`:

```bash
uv run --project etl python olap/benchmark/run_benchmark.py --label baseline
```

`evidence/benchmark/README.md` records the baseline medians, the bottlenecks
found in the plans, and the measured generic-plan hazard. Optimization
(secondary indexes, query reformulation, pre-aggregation) has not been applied
yet, so the "before" side of the comparison exists and the "after" side is
pending.

## Project status

Steps 1–4 are complete and Step 6 has its baseline; what is left is functional
testing, the optimization pass, and the report itself.

| Step | State |
|---|---|
| 1. Source database setup | Done — 3,109,927 rows imported, validated, and re-validated read-only |
| 2. Data warehouse construction | Done — 3 facts, 6 dimensions, 5 hierarchies, executable readiness gate |
| 3. ETL pipeline | Done — 1,000,000 deliveries + 1,999,824 order items + 36,500 rider-days, 15/15 reconciliation checks, 0 rejects |
| 4. OLAP application | Done — 12 parameterized query levels, the Go API, and the dashboard's four reports |
| 5. Functional testing | **Pending** — the dashboard has a column-contract suite and a rendered-report suite (`npm test`, 233 checks), a live contract check (`npm run check:contracts`) and a Go schema↔query contract test in CI; a report-level script that reconciles analytical results to the ETL baseline is still missing |
| 6. Performance testing | Baseline measured (18 cases, medians 66–8,224 ms) plus the generic-plan comparison; optimization and the before/after comparison **pending** |
| 7. Final technical report | **Pending** — evidence is indexed in `docs/technical-documentation/index.md`; the report template is not filled in |

`docs/project-checklist.md` carries the same status with the artifact behind
every checked item.
