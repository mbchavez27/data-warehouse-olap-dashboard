# Data Warehousing and OLAP Dashboard

Query Processing in a Data Warehouse. Covers ETL data wrangling, dimensional modeling, and an optimized web-based OLAP interface. | In Submission for STADVDB

## Tech Stack

- **Database:** PostgreSQL 16 (source database and data warehouse) deployed via Docker Compose.
- **ETL Pipeline:** Python with `uv` for fast dependency management.
- **Backend API:** Go 1.25 with the standard-library `net/http` router and `pgx/v5` (no web framework).
- **Frontend:** React 18 with Vite, no UI, chart or icon libraries.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Go](https://golang.org/doc/install) 1.25+
- [Node.js](https://nodejs.org/) 18+
- [Python](https://www.python.org/downloads/) 3.10+
- [uv](https://github.com/astral-sh/uv) (Extremely fast Python package installer and resolver)

## Setup Instructions

### 1. Database Initialization

The official dataset ZIP is too large for version control and is ignored by Git. Keep `MCO1_dataset_ecommerce.zip` outside the repository; do not extract or rename its contents. The importer reads the ZIP directly (expected SHA-256 `a10f1186...862`).

From the repository root (macOS/Linux, or Git Bash/WSL on Windows):

```bash
./db/scripts/setup_source.sh --archive "/absolute/path/MCO1_dataset_ecommerce.zip" --reset
```

The script creates `.env` from `.env.example` if missing (local-only, never commit it), starts `source_db` (PostgreSQL 16 @ `localhost:5433`) via `docker compose up -d --wait source_db`, then runs the importer tests, archive verification, atomic import (3,109,927 rows), and database validation. Re-running without flags (`./db/scripts/setup_source.sh`) re-checks env, container health, tests, and validation without touching data.

_Native Windows CMD/PowerShell (no bash): run the equivalent commands directly — `Copy-Item .env.example .env`, `docker compose up -d --wait source_db`, `uv run --project db pytest db/source/importer`, `uv run --project db python db/source/importer/cli.py verify --archive <zip>`, `uv run --project db python db/source/importer/cli.py import --archive <zip> --reset`, `uv run --project db python db/source/importer/cli.py validate`._

_Confirm: open `evidence/source-import-report.json` — top-level `passed` must be `true`. Full procedure and acceptance checklist: `docs/database/source-database-setup.md`._

### 2. Running the ETL Pipeline

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

### 3. Starting the Backend (Go OLAP API)

The Go service runs the parameterized OLAP report queries (roll-up, drill-down,
slice, dice, pivot) from `olap/queries` against the warehouse and serves them as
JSON. It treats those SQL files as the single source of the queries and opens
the warehouse read-only, with `plan_cache_mode = force_custom_plan` so a reused
prepared statement cannot fall back to a bad generic plan.

```bash
cd olap-backend
go run .
```

Configuration is read from the repository-root `.env` (or `olap-backend/.env`):
`DW_HOST`, `DW_PORT`, `DW_DB`, `DW_USER`, `DW_PASSWORD`, `API_PORT`,
`QUERY_TIMEOUT`, `DW_MAX_CONNS`, `CORS_ORIGINS`, `OLAP_QUERIES_DIR`. Defaults
target the Compose warehouse at `localhost:5434/dw_db`.

_The API is available at `http://localhost:8080`. `GET /api/health` reports
warehouse reachability and `GET /api/reports` lists every report and level. Run
the tests with `go test ./...`._

### 4. Starting the Frontend (React Dashboard)

The interactive dashboard lets users filter (slice and dice) and drill into the
analytical reports.

```bash
cd olap-frontend
npm install
npm run dev
```

_The dashboard is available at `http://localhost:3000`._

By default it renders built-in sample data (`src/api/mock.js`), so it runs
before the API is up. To load real warehouse results, create
`olap-frontend/.env.local` with `VITE_API_MODE=live` and restart; Vite proxies
every `/api/...` call to `http://localhost:8080` (`API_TARGET` overrides that),
so no CORS setup is needed in development.

R1 (Products & Categories) and R2 (Fleet & Rider Workload) are implemented;
R3 (Customer Value) and R4 (Demand Calendar) are wired to a placeholder while
their SQL and API levels are already available.

## Documentation

| Document | Covers |
|---|---|
| `docs/database/source-database-setup.md` | Source import procedure and acceptance checks |
| `docs/database/source-schema.md` | Source schema and wrangling issues |
| `docs/database/data-warehouse-schema.md` | Star schema, hierarchies, business questions, reports |
| `docs/database/data-warehouse-implementation.md` | Implemented warehouse types, constraints and load order |
| `olap/queries/README.md` | The four OLAP reports, their parameters and measures |
| `olap-frontend/README.md` | Dashboard layout and the API contract it expects |
| `evidence/benchmark/README.md` | Query baseline, plan bottlenecks and the generic-plan hazard |
| `docs/technical-documentation/index.md` | Evidence index for the final report |

## Testing and Optimization (Steps 5 & 6)

Test suites: `uv run --project etl pytest etl/tests` (ETL),
`uv run --project db pytest db/source/importer` (source importer), and
`go test ./...` in `olap-backend` (API). End-to-end report checks against the
dashboard are still to be added.

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
