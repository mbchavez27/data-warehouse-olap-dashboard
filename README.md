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

The raw SQL dumps are too large for version control and are ignored by Git. You must place them in the project manually before starting the environment.

1. Navigate to the `db/raw-dumps/` directory (the folder exists via `.gitkeep`).
2. Place your raw SQL dump files inside `db/raw-dumps/`.
3. Start the PostgreSQL instances:
   ```bash
   docker-compose up -d
   ```
   _Note: The `docker-compose.yml` mounts the `db/` folder to a volume and runs the initialization scripts (`01_source_schema.sql` and `02_dw_schema.sql`) to scaffold both the operational source database and the dimensional warehouse._

### 2. Running the ETL Pipeline

The ETL script extracts the raw data, applies data wrangling (handling nulls, aggregating, generating synthetic data if needed), and loads it into the Data Warehouse fact and dimension tables. We use `uv` for lightning-fast environment setup.

```bash
cd etl
uv venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
uv pip install -r requirements.txt
python main.py
```

_(Alternatively, you can skip activation and run directly with: `uv run main.py`)_

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
