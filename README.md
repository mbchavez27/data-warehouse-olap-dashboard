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

The ETL script extracts the raw data, applies data wrangling (handling nulls, aggregating, generating synthetic data if needed), and loads it into the Data Warehouse fact and dimension tables. We use `uv` for lightning-fast environment setup.

```bash
uv sync --project etl
uv run --project etl python etl/main.py --check
```

_The `--check` readiness gate (exact source counts + warehouse readiness) runs first; the full Extract/Transform/Load run command lands with the next ETL phase._

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
