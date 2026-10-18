# Functional tests

End-to-end checks of the loaded warehouse and the live API. They sit above the
unit tests (ETL, Go) and the Go schema-contract test, and answer one question:
**does the dashboard show the right numbers?**

## Run

```bash
docker compose up -d                                # source_db :5433, dw_db :5434
docker compose --profile app up -d --no-deps api    # API :8080
uv run --project etl python -m unittest discover -s olap/tests -v
```

Takes about 95 seconds. It is safe to re-run. Output is plain ASCII.

Useful variants:

```bash
cd olap/tests && uv run --project ../../etl python -m unittest test_report_correctness   # one file
python olap/tests/dwsupport.py                       # preflight + evidence header only
API=http://host:8080 ...                             # point at another API
```

A **preflight** runs first. It checks that both database containers are up, that
`/api/health` is `{"database":"ok","status":"ok"}`, and that both databases
answer `SELECT 1`. If not, every test fails at once with the list of what is
wrong, instead of 74 confusing connection errors.

## Files

| File | Tests | What it proves |
|---|---|---|
| `test_api_contract.py` | 17 | Catalog lists 4 reports / 12 levels with the right columns; aliases; every declared enum value is accepted and a bad one is a 400; 404s; free-text filters with no match give 200 and 0 rows; `city` needs `country`; SQL-looking text is bound as a value. |
| `test_warehouse_integrity.py` | 20 | `dw_db` against `source_db`: calendar attributes, unknown-member rows, dimension counts and attributes, no orphan keys, unique grain, row/unit/value totals, every order on the right day/rider/customer, line values, the rider-by-day grid, and each `AGG_*` view being an exact rollup of the base facts. |
| `test_report_correctness.py` | 37 | Every report level against an independent reference (about 115 filter combinations), pinned hand-checked figures, and internal consistency (parts sum to totals, ranks, shares, subtotals). |
| `dwsupport.py` | - | Shared helpers, the preflight, and the reference model. |

Coverage per report level: r1 category, product; r2 cube, pivot, rider;
r3 deciles, geography, customer; r4 rollup, trend (year, quarter, month, week,
day), weekday_pivot, busiest_days. All 12 are compared row by row with a
reference, with filters that include every year, quarter, vehicle, size group,
day type and payday option, and the sort and `top_n` variants.

## How the expected values are produced

The oracle is independent of the code under test:

* Expected rows come from **source_db** (the raw operational data) plus Python
  re-implementations of the report formulas in `dwsupport.py`.
* The tests never run the report SQL in `olap/queries/` or call the Go code to
  get an expected value.
* The source's known mess is normalised in the test (two `deliveryDate` formats,
  14 category spellings to 9, `Bike`/`Motorbike`, `Female`/`Male`), so an ETL
  that mishandled any of it would show up as a mismatch.
* The reference mirrors the report SQL's rounding (numeric half away from zero,
  `percent_rank` through float8, NTILE bucketing, RANK ties). Where a LIMITed
  list has tied values, the comparison accepts any order within a tie but still
  checks each row's values, rank and decile.
* A few figures are also pinned as literals and re-derived with SQL written
  inside the test (`TestPinned`), so a mistake in the reference model cannot
  hide a mistake in the warehouse.

## Read-only guarantee

Every `psql` session sets `default_transaction_read_only=on`. The suite never
writes to `dw_db` or `source_db`, and `TestReadOnlyGuard` proves it by checking
that a `CREATE TEMP TABLE` is refused on both.

## Negative control

To show the tests can fail, `DWTEST_NEGATIVE_CONTROL=1` makes the reference
drop one source order (as if the warehouse lost 1 of 1,000,000). Nothing in a
database changes.

```bash
DWTEST_NEGATIVE_CONTROL=1 uv run --project etl python -m unittest discover -s olap/tests
```

The suite must then fail. Evidence is in `evidence/functional-tests/`.

## Not covered (known gaps)

* The React dashboard UI (rendering, filter widgets, charts). These tests stop at
  the API's JSON.
* Performance. Timing and the optimization results are in `evidence/benchmark/`.
* Concurrency, load and API restart behavior. The API container has no restart policy.
* Free-text filter values are not validated by the API (an unknown category,
  country or city returns 200 with 0 rows). The tests pin this as current behavior.
* The ETL itself is checked through its output (the loaded warehouse), not by
  re-running it. Its own unit tests are in `etl/`. The Go layer's schema contract
  test is `olap-backend/internal/reports/schema_contract_integration_test.go`.
* The reference model re-implements the report formulas, so a flaw in the
  *specification* shared by both (for example how a week is defined) would not be
  caught. The pinned figures and the internal-consistency checks limit this.
