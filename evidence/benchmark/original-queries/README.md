# OLAP report queries

Four analytical reports over the warehouse (`dw_db`). Each report is a folder;
each file in it is one drill level of that report and returns a fixed set of
columns. Every filter and drill choice is a bound parameter; nothing is
concatenated into SQL.

| Report | Level files | OLAP operations | Advanced SQL |
|---|---|---|---|
| **R1 Product & Category Value** (`r1_product_category_value/`) | `category.sql` → `product.sql` | roll-up / drill-down (Category > Product), slice (period), dice (vehicle, size group, category) | `ROLLUP`, `GROUPING()`, `RANK() OVER (PARTITION BY …)`, window share of total |
| **R2 Fleet, Courier & Rider Workload** (`r2_fleet_courier_workload/`) | `courier_vehicle_cube.sql`, `courier_vehicle_pivot.sql` → `rider.sql` | pivot (courier × vehicle), drill-down (Courier > Vehicle > Rider), drill-across to the rider-day snapshot, slice, dice | `CUBE`, `GROUPING()`, conditional aggregation (`FILTER`), `PERCENT_RANK()`, `RANK()` |
| **R3 Customer Value Distribution** (`r3_customer_value_distribution/`) | `deciles.sql` → `geography.sql` (country → city) → `customer.sql` | drill-down (Deciles > Country > City > Customer), dice (country × gender, period) | `NTILE`, cumulative `SUM() OVER (ORDER BY …)`, `GROUPING SETS`, `PERCENT_RANK()` |
| **R4 Demand Calendar** (`r4_demand_calendar/`) | `rollup.sql`, `trend.sql` (year / quarter / month / week / day), `weekday_pivot.sql`, `busiest_days.sql` | roll-up / drill-down (Year > Quarter > Month > Week > Day), slice (weekend, payday), dice (vehicle, size group), pivot (month × weekday) | `ROLLUP`, `GROUPING SETS`, `GROUPING()`, `LAG()`, moving average (`ROWS BETWEEN 6 PRECEDING`), `FILTER` pivot, `RANK()` |

All five OLAP operations are covered; every report is parameter-driven.

## Parameters

- Each file's header lists its parameters and allowed values, then its
  output columns.
- Parameters are named (`:'year'`, `:'level'`, …), so a file runs as-is in
  `psql` with `-v name=value`. The API binds the same names as typed values.
- An empty string means "no filter" for that dimension. Each filter is
  written `(:'x' = '' OR column = :'x')`, so one statement serves every
  combination.
- `top_n` caps ranked detail rows (products per category, riders, customers,
  days). `sort` flips ranked levels between most and least.

## Running a level by hand

Pass every parameter in the file header; use an empty value for "all":

```bash
docker exec -i stadvdb-mco1-dw-db psql -X -U postgres -d dw_db \
  -v year=2025 -v quarter= -v month= -v vehicle=Motorcycle -v size_group= \
  < olap/queries/r1_product_category_value/category.sql
```

## Measures

- **List-price value** (`lineValue`) is quantity × current list price. The
  source keeps no historical price, so it is an indicative basket value, not
  revenue; label it "List-price value" in the dashboard.
- Orders come from `FACT_ORDERDELIVERY` (one row per order), units and value
  from `FACT_ORDERITEM` (one row per product in an order), and active days
  and peak days from `FACT_RIDERDAILY` (one row per rider per day).
- R4 normalizes every period to orders per calendar day, because the first
  and last months are partial (Sep 2024: 7 days, Sep 2025: 23 days) and
  calendar week 53 is a 1–2 day stub.
