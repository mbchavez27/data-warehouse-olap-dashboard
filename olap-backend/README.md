# OLAP backend (Go API)

The Go service runs the OLAP report queries in [`olap/queries/`](../olap/queries/README.md)
against the data warehouse and serves the rows as JSON. It is the only layer
that talks to `dw_db`; the dashboard talks only to this API.

The SQL files are the single source of the queries. The service loads them at
startup, translates each `:'name'` parameter into a bound `$n` placeholder, and
verifies that the parameters a file uses match the ones the catalog declares —
so a changed query fails at startup, not per request.

## Run it

```bash
cd olap-backend
go run .
```

The API listens on `http://localhost:8080`. It reads configuration from a `.env`
file in the working directory or the repository root, falling back to the
defaults below. The default connection targets the Compose warehouse on
`localhost:5434/dw_db`, so start `dw_db` first (`bash etl/run_etl.sh`).

```bash
go test ./...   # API handler + report catalog/validation tests (no database needed)
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `API_PORT` (or `PORT`) | `8080` | Listen port |
| `DW_HOST` | `localhost` | Warehouse host |
| `DW_PORT` | `5434` | Warehouse port |
| `DW_DB` | `dw_db` | Warehouse database |
| `DW_USER` | `postgres` | Warehouse user |
| `DW_PASSWORD` | `postgres` | Warehouse password |
| `DW_SSLMODE` | `disable` | libpq SSL mode |
| `QUERY_TIMEOUT` | `60s` | Per-request query timeout |
| `DW_MAX_CONNS` | `8` | Connection pool size |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Allowed browser origins |
| `OLAP_QUERIES_DIR` | auto (`../olap/queries`, then `olap/queries`) | Report SQL directory |

The pool is opened read-only (`default_transaction_read_only = on`) and with
`plan_cache_mode = force_custom_plan`. The latter avoids the generic-plan
slowdown measured in [`evidence/benchmark/README.md`](../evidence/benchmark/README.md):
a reused prepared statement can pick a plan that cannot tell which filters are
empty and then nested-loop over the whole fact table.

## Endpoints

| Method & path | Returns |
|---|---|
| `GET /api/health` | `{ "status": "ok", "database": "ok" }`, or `503` with `"degraded"` when the warehouse is unreachable |
| `GET /api/reports` | Catalog: every report, level, parameter and operation |
| `GET /api/reports/{report}` | One report's definition |
| `GET /api/reports/{report}/{level}?...` | One level's rows for the given filters |
| `GET /api/dimensions` | Filter values (`years`, `categories`, `couriers`, `vehicles`, `ageBands`, `sizeGroups`, `countries`, `genders`) |
| `GET /api/dimensions/cities?country=...` | Cities of one country, for the Country → City drill |

Report ids are `r1`–`r4`; a level also answers to its aliases (`r2/cube`,
`r2/pivot`). Filters left empty are treated as "all", matching the SQL's
`(:'x' = '' OR column = :'x')` pattern. Unknown parameters and out-of-range
values are rejected.

## Reports and levels

| Report | Level (aliases) | SQL file | Parameters |
|---|---|---|---|
| **r1** Product & Category Value | `category` | `r1_product_category_value/category.sql` | year, quarter, month, vehicle, size_group |
| | `product` | `r1_product_category_value/product.sql` | category, year, quarter, month, vehicle, size_group, top_n |
| **r2** Fleet, Courier & Rider Workload | `courier_vehicle_cube` (`cube`) | `r2_fleet_courier_workload/courier_vehicle_cube.sql` | year, quarter, month, courier, vehicle, age_band, size_group |
| | `courier_vehicle_pivot` (`pivot`) | `r2_fleet_courier_workload/courier_vehicle_pivot.sql` | measure, year, quarter, month, courier, vehicle, age_band, size_group |
| | `rider` | `r2_fleet_courier_workload/rider.sql` | year, quarter, month, courier, vehicle, age_band, sort, top_n |
| **r3** Customer Value Distribution | `deciles` | `r3_customer_value_distribution/deciles.sql` | country, gender, year, quarter |
| | `geography` | `r3_customer_value_distribution/geography.sql` | level, country, gender, year, quarter, top_n |
| | `customer` | `r3_customer_value_distribution/customer.sql` | country, city, gender, decile, year, quarter, top_n |
| **r4** Demand Calendar | `rollup` | `r4_demand_calendar/rollup.sql` | year, day_type, payday, vehicle, size_group |
| | `trend` | `r4_demand_calendar/trend.sql` | level, year, quarter, month, day_type, payday, vehicle, size_group |
| | `weekday_pivot` | `r4_demand_calendar/weekday_pivot.sql` | year, quarter, payday, vehicle, size_group |
| | `busiest_days` | `r4_demand_calendar/busiest_days.sql` | year, quarter, month, day_type, payday, vehicle, size_group, sort, top_n |

The allowed value of each parameter is in the SQL file header and in
`GET /api/reports`.

## Response

```json
{
  "report": "r1",
  "level": "category",
  "params": { "year": "2025", "quarter": "", "vehicle": "Motorcycle" },
  "columns": [
    { "name": "category", "type": "text" },
    { "name": "units", "type": "integer" }
  ],
  "rows": [ { "category": "Electronics", "units": 1234 } ],
  "rowCount": 11,
  "elapsedMs": 812.44
}
```

`columns` is in SQL order; each row's keys are the column names exactly.
`NUMERIC` keeps its exact decimal digits and `DATE` is `YYYY-MM-DD`.

## Errors

Failed requests return `{ "error": "message" }`, plus `details` for validation
problems. The dashboard shows the `error` string to the user.

| Status | Meaning |
|---|---|
| `400` | Unknown parameter or disallowed value; body includes the problems |
| `500` | Query failed (see the API log) |
| `503` | Warehouse unreachable |
| `504` | Query exceeded `QUERY_TIMEOUT` |

## Layout

```
main.go                    startup, config, pool, HTTP server
internal/api/server.go     routes, CORS, request logging, error mapping
internal/config/config.go  env loading and the warehouse DSN
internal/reports/
  catalog.go               the four reports, their levels and parameters
  sql.go                   load and translate the query files
  validate.go              parameter and cross-parameter validation
  service.go               run one level and shape the JSON result
  dimensions.go            filter-value lookups
```
