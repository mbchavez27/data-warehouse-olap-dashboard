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
- Fact→dimension FKs are enforced (fail-fast, same stance as the source
  importer): a bad ETL load aborts instead of silently orphaning facts.
- Money is `NUMERIC(12,2)` everywhere (`listPrice`, `lineValue`); the source
  `REAL` price is never summed directly (see `source-schema.md` issue 3).
- Source timestamps (`createdAt`/`updatedAt`) are bulk-load constants and are
  NOT modelled: the warehouse time dimension derives exclusively from
  `Orders.deliveryDate` (see `source-schema.md` issue 5).

## Table specs

### `DIM_DATE` (populated by ETL)

| Column | Type | Key / constraint |
|---|---|---|
| `dateKey` | `INTEGER` (`YYYYMMDD`) | PK |
| `fullDate` | `DATE NOT NULL` | UNIQUE |
| `dayOfMonth` | `SMALLINT NOT NULL` | — |
| `dayName` | `VARCHAR(9) NOT NULL` | — |
| `isWeekend` | `BOOLEAN NOT NULL` | — |
| `isPayDay` | `BOOLEAN NOT NULL` | rule below |
| `weekOfYear` | `SMALLINT NOT NULL` | — |
| `monthNumber` | `SMALLINT NOT NULL` | — |
| `monthName` | `VARCHAR(9) NOT NULL` | — |
| `quarter` | `SMALLINT NOT NULL` | — |
| `year` | `SMALLINT NOT NULL` | — |

Payday rule (Q14): `isPayDay` is true on the 15th and the last day of each
month (Philippine semimonthly payroll convention). The rule lives here so the
flag is deterministic and auditable; ETL implements it when building the date
dimension over `[min(deliveryDate), max(deliveryDate)]`.

### `DIM_RIDER`

| Column | Type | Key / constraint |
|---|---|---|
| `riderKey` | `INTEGER` identity | PK |
| `riderId` | `INTEGER NOT NULL` | UNIQUE |
| `fullName` | `VARCHAR(511) NOT NULL` | `firstName + ' ' + lastName` |
| `vehicleType` | `VARCHAR(32) NOT NULL` | Bicycle / Motorcycle / Car / Trike |
| `courierId` | `INTEGER NOT NULL` | — |
| `courierName` | `VARCHAR(255) NOT NULL` | — |
| `age` | `INTEGER` | nullable (source may lack it) |
| `ageBand` | `VARCHAR(16)` | kept: Q8/Q12 need rider bands; the profiling flag was customers-only |
| `gender` | `CHAR(1) NOT NULL` | normalized `M`/`F` (see `source-schema.md` issue 2) |

Unknown row: `(0, -1, 'Unknown', 'Unknown', -1, 'Unknown', NULL, 'Unknown', 'U')`.

### `DIM_GEOGRAPHY`

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

### `DIM_ORDERSIZE` (static seed in DDL)

| `orderSizeKey` | `sizeName` | `sizeGroup` | `minQuantity` | `maxQuantity` |
|---:|---|---|---:|---:|
| 1 | Small | Light | 1 | 1 |
| 2 | Medium | Light | 2 | 5 |
| 3 | Large | Heavy | 6 | 20 |
| 4 | Bulk | Heavy | 21 | 2147483647 |

Cutoffs are total order quantity (`SUM(quantity)` per order). Identity PK is
overridden to these fixed keys so facts and reports can rely on stable IDs.
Unknown row: `(0, 'Unknown', 'Unknown', 0, 0)` (excluded from Light/Heavy).

### `DIM_CUSTOMER`

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

### `DIM_PRODUCT`

| Column | Type | Key / constraint |
|---|---|---|
| `productKey` | `INTEGER` identity | PK |
| `productId` | `INTEGER NOT NULL` | UNIQUE |
| `productCode` | `VARCHAR(64) NOT NULL` | — |
| `productName` | `VARCHAR(255) NOT NULL` | — |
| `category` | `VARCHAR(128) NOT NULL` | — |
| `listPrice` | `NUMERIC(12,2) NOT NULL` | current list price |

Unknown row: `(0, -1, 'Unknown', 'Unknown', 'Unknown', 0.00)`.

### `FACT_ORDERDELIVERY` (one row per order)

`orderDeliveryKey BIGINT` identity PK; `orderNumber VARCHAR(255)` degenerate
dimension; FKs `deliveryDateKey → DIM_DATE`, `riderKey → DIM_RIDER`,
`geoKey → DIM_GEOGRAPHY`, `orderSizeKey → DIM_ORDERSIZE`,
`customerKey → DIM_CUSTOMER` (all `NOT NULL`, enforced); measures
`orderCount INTEGER NOT NULL DEFAULT 1` (always 1, additive),
`totalQuantity INTEGER NOT NULL`, `lineItemCount INTEGER NOT NULL`.

### `FACT_ORDERITEM` (one row per product in an order)

`orderItemKey BIGINT` identity PK; `orderNumber` degenerate; the five
parent-order FKs copied from the delivery grain plus
`productKey → DIM_PRODUCT` (all `NOT NULL`, enforced); measures
`quantity INTEGER NOT NULL`, `lineValue NUMERIC(12,2) NOT NULL`
(`quantity × current list price` — **indicative basket value, not revenue**,
because `OrderItems` carries no historical price).

### `FACT_RIDERDAILY` (one row per rider per delivery date, zero-order days included)

`riderDailyKey BIGINT` identity PK; FKs `dateKey → DIM_DATE`,
`riderKey → DIM_RIDER` (enforced); measures `ordersDelivered`,
`itemsDelivered` (`0` on idle days), `maxBasket` (non-additive: peak-day
basket, never summed across days), `isActiveDay SMALLINT 0/1`.
Idle days come from the rider×date cross join at ETL time (see grain note in
the design doc); the table shape already accommodates them.

## Profiling corrections applied

| # | Correction | DDL impact |
|---|---|---|
| 1 | Q20/Q21 geography conditional → report flat distribution | None (dimension built as designed) |
| 2 | Q22 customer age → concentration only | `DIM_CUSTOMER.ageBand` dropped |
| 3 | Q14 payday rule (15th + month-end) | `isPayDay` rule documented here, applied at ETL date-build |
| 4 | Idle-day grain (rider×date incl. zeros) | None (shape already fits; ETL cross-joins) |

## Fresh-volume verification (readiness gate, Report R0 pre-ETL half)

From the repository root (macOS/Linux, or Git Bash/WSL on Windows):

```bash
./db/scripts/setup_dw.sh
```

The script creates `.env` if missing, starts `dw_db` (PostgreSQL 16 @
`localhost:5434`), and runs the readiness gate in
`db/dw/validate/warehouse_readiness.sql`
(shared with the future ETL preflight), printing the JSON report and exiting
nonzero unless `passed` is true. Re-running without flags never touches data;
`--schema-only` re-applies the DDL (explicit, destructive).
Windows CMD/PowerShell: see the script header for the direct equivalents.

Note: volumes created before `01_dw_schema.sql` existed skip entrypoint init
(the `pg_dw_data` volume predates the file) — run `--schema-only` once to
converge those, then `passed` must be true.

Acceptance: 9 tables; dim column counts 11/9/4/5/6/6 (DATE/RIDER/GEO/ORDERSIZE/CUSTOMER/PRODUCT);fact column counts 10/10/7 (DELIVERY/ITEM/RIDERDAILY); 9 PKs; 13 enforced FKs (5 + 6 + 2);
5 key-0 Unknown rows (+ 4 static order-size bands); 0 fact rows; `DIM_DATE` empty
(range derives from source `deliveryDate` at ETL time). Scratch volumes are
removed with `docker compose down -v dw_db` only when intentionally wiping.

## Explicit non-scope

- No secondary indexes (Step 6 owns the baseline-vs-optimized experiment).
- No ETL loads and no DW data yet (next phase: `etl/` + `stadvdb-mco1-etl` env).
- Design-doc amendments for the customer-`ageBand` removal ship alongside
  this implementation (mermaid + hierarchy table + corrections note).
