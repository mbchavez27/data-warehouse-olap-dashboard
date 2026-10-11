# Data Warehouse Implementation (PostgreSQL)

Executable DDL: `db/dw/init/01_dw_schema.sql`. Design reference:
`docs/database/data-warehouse-schema.md`. The file below is the build record —
what was implemented, which approved corrections it carries, and how to verify
it from a fresh volume.

## Scope and conventions

- Star schema: 6 conformed dimensions + 3 fact tables (9 tables total).
- Identifiers are quoted UPPERCASE exactly as the design doc names them
  (same precedent as the source schema's quoted camelCase: no silent folding).
- `db/dw/init/01_dw_schema.sql` is auto-applied by Postgres on first volume
  init via `./db/dw/init:/docker-entrypoint-initdb.d:ro` (see
  `docker-compose.yml`, `dw_db` service).
- Idempotent: `DROP ... CASCADE` first, safe to re-run anytime and safe as an
  entrypoint script.
- Only PK/UNIQUE constraints ship in DDL. Secondary indexes (FK coverings,
  date roll-up paths) are deliberately deferred to Step 6 so the
  baseline-vs-optimized experiment starts from a clean floor.

## Key design

- `DIM_DATE.dateKey` is a smart key (`YYYYMMDD` integer), so ETL joins and
  date arithmetic need no lookup. All other dimensions use
  `INTEGER GENERATED ... AS IDENTITY` surrogates with a natural-key `UNIQUE`.
- Fact keys are `BIGINT GENERATED ... AS IDENTITY` per the design doc.
- Every dimension ships a key-0 `Unknown` row (`OVERRIDING SYSTEM VALUE`),
  so ETL maps unparseable or missing references to `0`, never to NULL FKs.
  Identity sequences restart past seeded keys (`1`, `5` for order-size bands)
  so generated values never collide with seeds.
- Fact→dimension FKs are enforced (fail-fast, same stance as the source
  importer): a bad ETL load aborts instead of silently orphaning facts.
- Money is `NUMERIC(12,2)` everywhere (`listPrice`, `lineValue`); the source
  `REAL` price is never summed directly (see `source-schema.md` issue 3).
- Source timestamps (`createdAt`/`updatedAt`) are bulk-load constants and are
  NOT modelled: the warehouse time dimension derives exclusively from
  `Orders.deliveryDate` (see `source-schema.md` issue 5).

## Table specs

### `DIM_DATE` (populated by `etl/main.py --date`)

| Column | Type | Key / constraint |
|---|---|---|
| `dateKey` | `INTEGER` (`YYYYMMDD`) | PK |
| `fullDate` | `DATE NOT NULL` | UNIQUE |
| `dayOfMonth` | `SMALLINT NOT NULL` | — |
| `dayName` | `VARCHAR(9) NOT NULL` | — |
| `isWeekend` | `BOOLEAN NOT NULL` | — |
| `isPayDay` | `BOOLEAN NOT NULL` | rule below |
| `weekOfYear` | `SMALLINT NOT NULL` | calendar week, rule below |
| `monthNumber` | `SMALLINT NOT NULL` | — |
| `monthName` | `VARCHAR(9) NOT NULL` | — |
| `quarter` | `SMALLINT NOT NULL` | — |
| `year` | `SMALLINT NOT NULL` | — |

Payday rule (Q14): `isPayDay` is true on the 15th and the last day of each
month (Philippine semimonthly payroll convention). The rule lives here so the
flag is deterministic and auditable; ETL implements it when building the date
dimension over `[min(deliveryDate), max(deliveryDate)]`.

Week rule (Year > Week > Day hierarchy): `weekOfYear` is a calendar week,
`(day of year − 1) / 7 + 1`. Jan 1–7 is always week 1, so a week never
crosses into another `year` and the hierarchy rolls up cleanly. The last
week of a year is partial: week 53 holds 1 day (2 in leap years), e.g.
2024-12-30 and 2024-12-31. Weekly reports should compare per-day averages,
or exclude week 53, so the short week does not read as a demand drop.

The loader parses the two measured source formats (`YYYY-MM-DD` and
`MM/DD/YYYY`) before deriving the range. It rejects missing, malformed, and
calendar-invalid values because `DIM_DATE` intentionally has no key-0 Unknown
member. It then expands the parsed minimum and maximum to every consecutive
calendar day, including dates with no orders, and replaces `DIM_DATE` using
`DELETE` + bulk `INSERT` in one transaction. The current official dataset
measures `2024-09-24` through `2025-09-23` (365 rows), but those endpoints are
validated results, not hardcoded loader inputs.

### `DIM_RIDER` (populated by `etl/main.py --dims`)

| Column | Type | Key / constraint |
|---|---|---|
| `riderKey` | `INTEGER` identity | PK |
| `riderId` | `INTEGER NOT NULL` | UNIQUE |
| `fullName` | `VARCHAR(511) NOT NULL` | `firstName + ' ' + lastName` |
| `vehicleType` | `VARCHAR(32) NOT NULL` | Bicycle / Motorcycle / Car / Trike |
| `courierId` | `INTEGER NOT NULL` | — |
| `courierName` | `VARCHAR(255) NOT NULL` | — |
| `age` | `INTEGER` | nullable (source may lack it) |
| `ageBand` | `VARCHAR(16)` | decade bands, rule below; kept for Q8/Q12 (the profiling flag was customers-only) |
| `gender` | `CHAR(1) NOT NULL` | normalized `M`/`F` (see `source-schema.md` issue 2) |

Unknown row: `(0, -1, 'Unknown', 'Unknown', -1, 'Unknown', NULL, 'Unknown', 'U')`.

Vehicle cleanup: the source spells two vehicles two ways. `Bike` → `Bicycle`
and `Motorbike` → `Motorcycle`; `Car` and `Trike` pass through. Result: 4
vehicles (Motorcycle 42, Bicycle 29, Car 15, Trike 14 riders).

Age-band rule: decade bands `18-29`, `30-39`, `40-49`, `50-60` (20 / 26 / 23 /
31 riders on the official data). Decades read naturally on a dashboard, and
with only 100 riders every band still holds at least 20 riders, so band
comparisons are not driven by a handful of people. A narrower scheme (e.g. a
`55+` band) would leave single-digit groups.

### `DIM_GEOGRAPHY` (populated by `etl/main.py --dims`)

| Column | Type | Key / constraint |
|---|---|---|
| `geoKey` | `INTEGER` identity | PK |
| `country` | `VARCHAR(128) NOT NULL` | part of natural UNIQUE |
| `city` | `VARCHAR(128) NOT NULL` | part of natural UNIQUE |
| `zipCode` | `VARCHAR(32) NOT NULL` | part of natural UNIQUE |

`UNIQUE (country, city, zipCode)`. Unknown row: `(0, 'Unknown', 'Unknown', 'Unknown')`.
Profiling note: source geography is approximately uniform, so Q20/Q21 read
flat — the dimension is still built (drill-down paths must exist); the
questions report the flat distribution as the finding.

Hierarchy: Country > City. Every `zipCode` is unique to one customer
(100,000 triples for 100,000 users), so a zip level would only list single
customers; it stays as an attribute, not a drill level. City names repeat
across countries, so reports always group a city together with its country.

### `DIM_ORDERSIZE` (static seed in DDL)

| `orderSizeKey` | `sizeName` | `sizeGroup` | `minQuantity` | `maxQuantity` |
|---:|---|---|---:|---:|
| 1 | Small | Light | 1 | 6 |
| 2 | Medium | Light | 7 | 10 |
| 3 | Large | Heavy | 11 | 15 |
| 4 | Bulk | Heavy | 16 | 2147483647 |

Cutoffs are total order quantity (`SUM(quantity)` per order), set at the
measured quartiles of the official data (25% ≤ 6, median 10, 75% ≤ 15; max
34). The bands hold 25.6% / 26.7% / 23.5% / 24.2% of orders, and the Light /
Heavy split falls at the median (52.3% / 47.7%). The original cutoffs (1 /
2–5 / 6–20 / 21+) put 72% of orders in Large, which left slices by size with
almost nothing to compare. Identity PK is
overridden to these fixed keys so facts and reports can rely on stable IDs.
Unknown row: `(0, 'Unknown', 'Unknown', 0, 0)` (excluded from Light/Heavy).

### `DIM_CUSTOMER` (populated by `etl/main.py --dims`)

| Column | Type | Key / constraint |
|---|---|---|
| `customerKey` | `INTEGER` identity | PK |
| `customerId` | `INTEGER NOT NULL` | UNIQUE |
| `username` | `VARCHAR(255) NOT NULL` | — |
| `firstName` | `VARCHAR(255)` | — |
| `lastName` | `VARCHAR(255)` | — |
| `gender` | `CHAR(1)` | normalized `M`/`F`, nullable |

No `ageBand`: source customers are effectively single-age (profiling), so the
column would be constant. The hierarchy collapses to Gender; Q22 answers the
concentration half only. Unknown row: `(0, -1, 'Unknown', 'Unknown', 'Unknown', NULL)`.

### `DIM_PRODUCT` (populated by `etl/main.py --dims`)

| Column | Type | Key / constraint |
|---|---|---|
| `productKey` | `INTEGER` identity | PK |
| `productId` | `INTEGER NOT NULL` | UNIQUE |
| `productCode` | `VARCHAR(64) NOT NULL` | — |
| `productName` | `VARCHAR(255) NOT NULL` | — |
| `category` | `VARCHAR(128) NOT NULL` | — |
| `listPrice` | `NUMERIC(12,2) NOT NULL` | current list price, rounded to centavos |

Unknown row: `(0, -1, 'Unknown', 'Unknown', 'Unknown', 0.00)`.

Category cleanup: the source spells four categories several ways. Labels
that differ only in case, spacing, or singular/plural merge (`TOYS`/`Toy`/
`Toys` → `Toys`, `BAG`/`Bags` → `Bags`, `make up`/`Makeup` → `Makeup`,
`GADGETS`/`Gadgets` → `Gadgets`); distinct concepts stay separate (`Clothes`
vs `Men's Apparel`, `Gadgets` vs `Electronics`), since merging those would be
interpretation, not cleaning. Result: 9 categories covering all 10,000
products.

Price rounding: the dump stores MySQL `FLOAT` prices with up to 5 decimals
(e.g. `1.77046`; 920 of 10,000 products have more than 2). `listPrice` rounds
half away from zero to 2 decimals in SQL (`price::numeric(12,2)`), so
`1.77046` → `1.77` and `3.27517` → `3.28`.

### `FACT_ORDERDELIVERY` (one row per order; populated by `etl/main.py --facts`)

`orderDeliveryKey BIGINT` identity PK; `orderNumber VARCHAR(255)` degenerate
dimension; FKs `deliveryDateKey → DIM_DATE`, `riderKey → DIM_RIDER`,
`geoKey → DIM_GEOGRAPHY`, `orderSizeKey → DIM_ORDERSIZE`,
`customerKey → DIM_CUSTOMER` (all `NOT NULL`, enforced); measures
`orderCount INTEGER NOT NULL DEFAULT 1` (always 1, additive),
`totalQuantity INTEGER NOT NULL`, `lineItemCount INTEGER NOT NULL`.
`geoKey` is the customer's address (`Users`), the only location in the source
(decision D12). `orderSizeKey` is looked up from `DIM_ORDERSIZE` by
`totalQuantity`, so the seed rows stay the single source of the cutoffs.

### `FACT_ORDERITEM` (one row per product in an order; populated by `etl/main.py --facts`)

`orderItemKey BIGINT` identity PK; `orderNumber` degenerate; the five
parent-order FKs copied from the delivery grain plus
`productKey → DIM_PRODUCT` (all `NOT NULL`, enforced); measures
`quantity INTEGER NOT NULL`, `lineValue NUMERIC(12,2) NOT NULL`
(`quantity × current list price` — **indicative basket value, not revenue**,
because `OrderItems` carries no historical price). The multiplier is the
rounded `DIM_PRODUCT.listPrice`, so `lineValue` reconciles exactly against the
warehouse's own price column.

### `FACT_RIDERDAILY` (one row per rider per delivery date, zero-order days included; populated by `etl/main.py --facts`)

`riderDailyKey BIGINT` identity PK; FKs `dateKey → DIM_DATE`,
`riderKey → DIM_RIDER` (enforced); measures `ordersDelivered` (orders that
day), `itemsDelivered` (total units, `SUM(quantity)`, the same unit as
`FACT_ORDERDELIVERY.totalQuantity`), `maxBasket` (units in the rider's largest
single order that day; non-additive, never summed across days),
`isActiveDay SMALLINT 0/1`. All measures are `0` on idle days. Product counts
are not repeated here: they stay in `FACT_ORDERDELIVERY.lineItemCount`
(drill-across through `DIM_DATE` and `DIM_RIDER`).
It is built inside the warehouse from `FACT_ORDERDELIVERY` (decision D14):
every real rider × every `DIM_DATE` day, left-joined to that rider's daily
order totals, so the snapshot cannot disagree with the order fact. The official data has no idle rider-days (all 100 riders
deliver on all 365 days), so the zero-row path is proven by a unit-test
fixture and the live load is checked by counts: 36,500 rows, 1,000,000 orders
in total, 0 idle rows.

## Profiling corrections applied

| # | Correction | DDL impact |
|---|---|---|
| 1 | Q20/Q21 geography conditional → report flat distribution | None (dimension built as designed) |
| 2 | Q22 customer age → concentration only | `DIM_CUSTOMER.ageBand` dropped |
| 3 | Q14 payday rule (15th + month-end) | `isPayDay` rule documented here, applied at ETL date-build |
| 4 | Idle-day grain (rider×date incl. zeros) | None (shape already fits; ETL cross-joins) |
| 5 | Order-size cutoffs moved to the data's quartiles (1–6 / 7–10 / 11–15 / 16+) | `DIM_ORDERSIZE` seed rows |
| 6 | Calendar weeks (Jan 1–7 = week 1) so Year > Week never crosses a year | None (ETL date-build rule) |
| 7 | Geography drills Country > City; zip kept as an attribute | None (reporting rule) |

## ETL run order and performance

Fresh build, in order (each mode runs the preflight first):

| Step | Command | Result on the official data | Time |
|---|---|---|---:|
| 1 | `etl/main.py --date` | 365 dates | < 1 s |
| 2 | `etl/main.py --dims` | 100 riders, 100,000 geographies, 100,000 customers, 10,000 products | ~5 s |
| 3 | `etl/main.py --facts` | 1,000,000 orders, 1,999,824 order items, 36,500 rider-days | ~30 s |

A full rebuild from an empty warehouse takes about 40 s. Reruns are
idempotent: `--dims` upserts in place, and `--facts` truncates and reloads all
three facts in one transaction (identities restart, so a second reload is
byte-identical).

Fact-load design:
- Orders and order items stream from the source in 10,000-row batches through
  server-side cursors; no table is read whole into memory.
- Natural references resolve to surrogate keys through in-memory maps built
  from the loaded dimensions (365 dates, 100 riders, 100,000 customers and
  their addresses, 10,000 products). The source and warehouse are separate
  databases, so a SQL join across them is not possible.
- Rows arrive through `COPY`, the fastest bulk path into PostgreSQL.
- **Foreign keys are suspended during the bulk copy and re-added before
  commit.** Checking 13 FKs row by row (about 12 million single-row lookups)
  made the first version take 3 min 56 s. Re-adding the constraints validates
  every row in one set-based pass (1.4 s), cutting the load to 14 s with the
  same integrity guarantee. Both steps sit inside the load transaction: if
  validation fails, the rows and the dropped constraints roll back together
  (covered by a test).
- Before commit the load verifies its own output: row counts equal the source
  (orders, order items, riders × dates) and five consistency checks hold
  (rider-day orders = deliveries, rider-day units = delivered units, item units
  = delivered units, item rows = line-item count, `lineValue = quantity ×
  listPrice`). Any failure aborts the load.

Independent check against the source after the load: 10,999,917 units in the
source equal the units in all three facts; per-day order counts (365 days) and
per-rider order counts match exactly.

## Fresh-volume verification (readiness gate, Report R0 pre-ETL half)

From the repository root (macOS/Linux, or Git Bash/WSL on Windows):

```bash
./db/scripts/setup_dw.sh
```

The script creates `.env` if missing, starts `dw_db` (PostgreSQL 16 @
`localhost:5434`), and runs the readiness gate in
`db/dw/validate/warehouse_readiness.sql`
(shared with the ETL preflight), printing the JSON report and exiting
nonzero unless `structurallyReady` is true; it then reports whether facts are
loaded. `passed` (structure and empty facts) is the pre-load verdict that
`--date` requires. Re-running without flags never touches data;
`--schema-only` re-applies the DDL (explicit, destructive).
Windows CMD/PowerShell: see the script header for the direct equivalents.

Note: volumes created before `01_dw_schema.sql` existed skip entrypoint init
(the `pg_dw_data` volume predates the file) — run `--schema-only` once to
converge those, then `passed` must be true.

Acceptance: 9 tables; dim column counts 11/9/4/5/6/6
(DATE/RIDER/GEO/ORDERSIZE/CUSTOMER/PRODUCT); fact column counts 10/10/7
(DELIVERY/ITEM/RIDERDAILY); 9 PKs; 13 enforced FKs (5 + 6 + 2); 5 key-0
Unknown rows (+ 4 static order-size bands); and 0 fact rows. `dimDateRows` is
reported but deliberately not part of the pass/fail conjunction: a fresh
schema has 0 rows, while `etl/main.py --date` populates the runtime-derived
calendar range and must remain structurally ready on rerun. Scratch volumes
are removed with `docker compose down -v dw_db` only when intentionally wiping.

## Explicit non-scope

- No secondary indexes (Step 6 owns the baseline-vs-optimized experiment).
- `--date` loads `DIM_DATE` (before facts only); `--dims` upserts the four
  source-driven dimensions by natural key in one transaction (SCD Type 1:
  changed attributes overwrite in place, surrogate keys never change, rows
  are never deleted). The five static `DIM_ORDERSIZE` rows remain DDL-owned
  and are verified, not rebuilt, by the date loader. `--facts` reloads all
  three facts.
- Rejected source rows abort the load before commit and are listed in
  `evidence/etl-rejects.json` (empty on the official dataset).
- Design-doc amendments for the customer-`ageBand` removal ship alongside
  this implementation (mermaid + hierarchy table + corrections note).
