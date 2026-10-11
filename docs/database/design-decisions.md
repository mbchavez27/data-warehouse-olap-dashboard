# Design Decisions Log

One place for every data-warehouse and ETL decision, why it was made, and who
made it. Details and verification live in the linked docs:
`data-warehouse-schema.md` (design), `data-warehouse-implementation.md`
(build record), `source-schema.md` (source issues).

**Who decided:**
- **Team**: decided by the group.
- **Team (AI-prepared options)**: the group chose after AI laid out the options and trade-offs.
- **AI-assisted**: proposed by AI with its rationale, then reviewed and adopted by the group.

Declare every AI-assisted row in the report's GenAI declaration (§9.1).

## Dimensional model

| # | Decision | Why | Who decided |
|---|---|---|---|
| D1 | Star schema: 3 facts (`FACT_ORDERDELIVERY`, `FACT_ORDERITEM`, `FACT_RIDERDAILY`) sharing 6 conformed dimensions | One star per business process (order, order line, rider-day); shared dimensions allow drill-across (Q16) | Team |
| D2 | Smart date key `YYYYMMDD`; other dimensions use identity surrogate keys with a natural-key `UNIQUE` | Date keys need no lookup and sort naturally; surrogates isolate the warehouse from source IDs | Team |
| D3 | Every dimension has a key-0 `Unknown` row (`DIM_DATE` has none) | Facts never need NULL foreign keys | Team |
| D4 | Money is `NUMERIC(12,2)`; `lineValue` is labeled indicative basket value, not revenue | Exact arithmetic; `OrderItems` carries no historical price | Team |
| D5 | Customer `ageBand` dropped | Every source customer is about the same age, so the column would be constant | Team |
| D6 | Payday = 15th and last day of each month | Philippine semimonthly payroll convention (Q14) | Team |
| D7 | `FACT_RIDERDAILY` includes zero-order days (rider × date) | A periodic snapshot must show idle capacity, not just activity | Team |
| D8 | Calendar weeks: Jan 1–7 = week 1, so a week never crosses a year | ISO weeks under the calendar year put 2024-12-30/31 in "2024 week 1"; calendar weeks keep Year > Week clean without a schema change. Trade-off: week 53 is a 1–2 day partial week, so weekly reports compare per-day averages | Team (AI-prepared options) |
| D9 | Order-size bands at the data's quartiles: Small 1–6, Medium 7–10, Large 11–15, Bulk 16+; Light ≤ 10, Heavy ≥ 11 | The original cutoffs put 72% of orders in Large; quartiles give ~25% per band and a median Light/Heavy split, so size slices have real contrast | AI-assisted |
| D10 | Rider age bands by decade: 18–29, 30–39, 40–49, 50–60 | Natural labels; with 100 riders every band still has ≥ 20 riders (20/26/23/31) | AI-assisted |
| D11 | Geography drills Country > City; zip stays an attribute | Every zip belongs to one customer, so a zip level shows single customers; city names repeat across countries, so a city is always grouped with its country | AI-assisted |
| D12 | An order's geography is its customer's address (`Users`) | `Orders` has no delivery address; the customer address is the only location in the source | AI-assisted |
| D13 | `FACT_RIDERDAILY` measures: `itemsDelivered` = units, `maxBasket` = units in the rider's largest single order that day; no extra product-count column | Units match `totalQuantity`; product counts per order are flat (1/2/3 products, ⅓ each) and already in `FACT_ORDERDELIVERY.lineItemCount` | AI-assisted |
| D14 | `FACT_RIDERDAILY` is built inside the warehouse from `FACT_ORDERDELIVERY` | The snapshot cannot disagree with the order fact it summarizes, and needs no second pass over the source | AI-assisted |

## ETL

| # | Decision | Why | Who decided |
|---|---|---|---|
| E1 | Dates parse strictly from two formats (`YYYY-MM-DD`, `MM/DD/YYYY`); anything else aborts | Measured: the source uses exactly these two; there is no date-0 Unknown member to fall back on | Team |
| E2 | Gender normalizes to `M`/`F` from M/F/Male/Female | Same four spellings in `Riders` and `Users` | Team |
| E3 | Vehicle and category cleanup merges only spelling, case, spacing and plural variants (6 → 4 vehicles, 14 → 9 categories) | Fixes data-entry noise without inventing groupings; distinct concepts (Clothes vs Men's Apparel, Gadgets vs Electronics) stay separate | AI-assisted |
| E4 | Prices round half-up to centavos from their text form; `lineValue` uses the rounded `listPrice` | 920 prices carry up to 5 decimals; text avoids binary-float tie errors; the rounded price lets `lineValue` reconcile exactly inside the warehouse (catalog total moves only ₱0.42) | AI-assisted |
| E5 | Any unresolvable row (bad value, missing reference, orphan) aborts the whole load before commit, and every reject is written to `evidence/etl-rejects.json` | Mapping bad rows to `Unknown` would make reports look complete while data is missing; aborting keeps totals honest, the ledger shows exactly what to fix, and the enforced FKs back it up. The official data has 0 rejects | AI-assisted |
| E6 | Dimensions upsert by natural key (SCD Type 1: overwrite, never delete); facts fully reload in one transaction | Surrogate keys stay stable across reruns; reruns are idempotent | Team (ticket), AI-assisted (implementation) |
| E7 | Two readiness verdicts: `passed` (pre-load, facts empty) and `structurallyReady` (shape only) | Reload modes must rerun after facts exist; the pre-load gate stays strict for `--date` | AI-assisted |
| E8 | No idle rider-day exists in the source, so the idle path is proven by a test fixture and the live load by counts (riders × dates rows, 0 idle) | The ticket's "sample a known idle date" cannot be met on this data; a fixture plus counts proves the logic and verifies the "no idle riders" finding | AI-assisted |

## Deferred to Step 6

| Decision | Why |
|---|---|
| No secondary indexes in the base DDL | The baseline-vs-optimized experiment must start from a clean floor |
