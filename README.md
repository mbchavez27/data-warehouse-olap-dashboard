# Data Warehousing and OLAP Dashboard

Query Processing in a Data Warehouse. Covers ETL data wrangling, dimensional modeling, and an optimized web-based OLAP interface. | In Submission for STADVDB

## Tech Stack

- **Database:** PostgreSQL (Source Database & Data Warehouse) deployed via Docker.
- **ETL Pipeline:** Python with `uv` for fast dependency management.
- **Backend API:** Go (Gorilla Mux/Chi or standard `net/http`).
- **Frontend:** React.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Go](https://golang.org/doc/install) 1.20+
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
warehouse safety script.

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

The Go service handles the complex OLAP queries (roll-up, drill-down, slice, dice) against the Data Warehouse.

```bash
cd backend
go mod tidy
go run main.go
```

_The API will be available at `http://localhost:8080`_

### 4. Starting the Frontend (React Dashboard)

The interactive dashboard allows users to dynamically filter and view analytical reports.

```bash
cd frontend
npm install
npm run dev
```

_The dashboard will be available at `http://localhost:3000`_

## Testing and Optimization (Steps 5 & 6)

All testing scripts are located in the `tests/` directory.

- **Functional Testing:** Run `uv run tests/functional_test.py` to verify query correctness against expected parameters.
- **Performance Testing:** Run `uv run tests/perf_test.py` to execute queries multiple times and record latency.
- **Optimization:** Apply secondary indexes by running `db/03_indexes.sql` on the Data Warehouse, then re-run the performance tests to measure the execution time improvements.
