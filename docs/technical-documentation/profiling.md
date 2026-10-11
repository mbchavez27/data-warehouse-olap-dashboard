# Source Profiling Findings and Applied Corrections

This is the canonical record for the source characteristics that changed the
warehouse design. The measurements below came from read-only SQL against the
official imported `source_db` on 2026-10-11. The dataset identity and row
counts are independently fixed by
[`source-import-report.json`](../../evidence/source-import-report.json).

## Measured findings

### PRF-1 — `createdAt` is load metadata, not business-event time

The timestamps are compressed into the dataset-generation/import window and
repeat across large batches. They are not literally one value in every large
table, so calling every value “constant” would be inaccurate.

| Source table | Rows | Distinct `createdAt` | Minimum | Maximum |
|---|---:|---:|---|---|
| Couriers | 3 | 1 | 2025-09-22 16:56:36 | 2025-09-22 16:56:36 |
| Riders | 100 | 1 | 2025-09-22 16:56:36 | 2025-09-22 16:56:36 |
| Users | 100,000 | 24 | 2025-09-22 16:56:11 | 2025-09-22 16:56:34 |
| Products | 10,000 | 3 | 2025-09-22 16:56:34 | 2025-09-22 16:56:36 |
| Orders | 1,000,000 | 433 | 2025-09-22 16:56:36 | 2025-09-22 17:03:48 |
| OrderItems | 1,999,824 | 433 | 2025-09-22 16:56:36 | 2025-09-22 17:03:48 |

**Consequence:** warehouse time analysis derives from `Orders.deliveryDate`.
Delivery speed, SLA duration, and hour-of-day reports are out of scope because
the source has no trustworthy order-event timestamp.

### PRF-2 — Customers form one narrow age cohort

The 100,000 customer birth dates cover exactly 365 distinct dates from
2006-09-29 through 2007-09-28. At the maximum delivery date, 2025-09-23,
customers are only 17 or 18 years old. This is not literally one exact age,
but it is too narrow for meaningful age-band comparison.

**Consequence:** `DIM_CUSTOMER.ageBand` was removed and Q22 is limited to
customer-concentration analysis. Rider age remains usable and is modeled in
`DIM_RIDER` because its measured range is broader.

### PRF-3 — Customer geography is high-cardinality and nearly uniform

| Measure | Result |
|---|---:|
| Customers | 100,000 |
| Distinct country/city/zip triples | 100,000 |
| Countries | 249 |
| Customers per country, min / max / mean | 351 / 449 / 401.61 |
| Country-city pairs | 99,032 |
| Customers per country-city, min / max / mean | 1 / 4 / 1.01 |

Every customer has a distinct geography triple, country totals are tightly
balanced, and almost every country-city pair belongs to one customer.

**Consequence:** the Country → City hierarchy remains available for required
drill-down, while zip code stays an attribute. Q20/Q21 must report the measured
flatness and high cardinality rather than claim an unsupported hotspot.

### PRF-4 — Demand is unusually flat

Order line counts are almost an exact one-third split: 333,593 orders have one
line, 333,091 have two, 333,215 have three, and only 101 have four. Across 365
delivery days, daily orders range from 2,588 to 2,888, with a mean of 2,739.73
and population standard deviation of 51.15 (about 1.87% of the mean).

**Consequence:** reports must treat weak variation as a valid result instead of
inventing seasonality or peaks. The periodic rider-day fact still materializes
the complete rider × date grid so zero-activity days would remain visible in a
less dense or future dataset.

## Applied warehouse corrections

| ID | Correction | Reason and implementation |
|---|---|---|
| COR-1 | Remove customer `ageBand` | PRF-2 provides no meaningful customer age segmentation; `DIM_CUSTOMER` retains customer identity and gender. |
| COR-2 | Define `isPayDay` as the 15th and calendar month-end | A deterministic analytical calendar rule supports Q14 and is derived during `DIM_DATE` loading. It is a declared modeling rule, not a source field. |
| COR-3 | Include idle days in the rider-day grain | `FACT_RIDERDAILY` is a periodic snapshot built from every rider × every warehouse date; absent activity produces zero measures instead of a missing row. |
| COR-4 | Report flat geography explicitly | The geography dimension and Country → City drill path remain, but Q20/Q21 disclose PRF-3 rather than overstate geographic concentration. |

Related, separately justified modeling rules—order-size quartiles, calendar
week numbering, rider age bands, and zip-code treatment—remain in
[`design-decisions.md`](../database/design-decisions.md).

## Reproduction queries

Rerun these measurements only after confirming that source evidence still
reports the official archive hash and exact row counts; otherwise the results
belong to a different dataset state. Dates use the same two formats accepted by
the ETL: `YYYY-MM-DD` and `MM/DD/YYYY`.

```sql
-- PRF-1: run once per source table, substituting its quoted name.
SELECT count(*) AS rows,
       count(DISTINCT "createdAt") AS distinct_created_at,
       min("createdAt"), max("createdAt")
FROM "Orders";
```

```sql
-- PRF-2
WITH parsed AS (
  SELECT CASE
    WHEN "dateOfBirth" ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
      THEN to_date("dateOfBirth", 'YYYY-MM-DD')
    WHEN "dateOfBirth" ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
      THEN to_date("dateOfBirth", 'MM/DD/YYYY')
  END AS dob
  FROM "Users"
)
SELECT min(dob), max(dob), count(DISTINCT dob),
       min(date_part('year', age(DATE '2025-09-23', dob))::int) AS min_age,
       max(date_part('year', age(DATE '2025-09-23', dob))::int) AS max_age
FROM parsed;
```

```sql
-- PRF-3
WITH country_counts AS (
  SELECT country, count(*) AS n FROM "Users" GROUP BY country
), city_counts AS (
  SELECT country, city, count(*) AS n FROM "Users" GROUP BY country, city
)
SELECT count(DISTINCT (country, city, "zipCode")) AS geographies,
       (SELECT count(*) FROM country_counts) AS countries,
       (SELECT min(n) FROM country_counts) AS country_min,
       (SELECT max(n) FROM country_counts) AS country_max,
       (SELECT avg(n) FROM country_counts) AS country_mean,
       (SELECT count(*) FROM city_counts) AS country_city_pairs,
       (SELECT max(n) FROM city_counts) AS city_max
FROM "Users";
```

```sql
-- PRF-4
WITH line_counts AS (
  SELECT "OrderId", count(*) AS lines FROM "OrderItems" GROUP BY "OrderId"
), daily AS (
  SELECT CASE WHEN "deliveryDate" ~ '^[0-9]{4}-'
         THEN to_date("deliveryDate", 'YYYY-MM-DD')
         ELSE to_date("deliveryDate", 'MM/DD/YYYY') END AS delivery_date,
         count(*) AS orders
  FROM "Orders" GROUP BY 1
)
SELECT (SELECT jsonb_object_agg(lines, orders)
        FROM (SELECT lines, count(*) AS orders
              FROM line_counts GROUP BY lines) x) AS lines_per_order,
       count(*) AS delivery_days, min(orders), max(orders),
       avg(orders), stddev_pop(orders)
FROM daily;
```
