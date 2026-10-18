# OLAP dashboard (React)

The web dashboard for the four warehouse reports. Built with React 18 and Vite,
no UI, chart or icon libraries: the tables, bars, pivot heat map, line chart,
demand calendar and icons are plain components so every part is easy to explain
in the demo.

## Run it

```bash
cd olap-frontend
npm install
npm run dev
```

Open http://localhost:3000.

By default the dashboard shows **sample data** (`src/api/mock.js`), so it works
before the Go API exists. To use real warehouse results once the API is up on
port 8080, create `olap-frontend/.env.local` with:

```
VITE_API_MODE=live
```

and restart `npm run dev`. Vite forwards every `/api/...` call to
`http://localhost:8080` (set `API_TARGET` to change that), so the Go API does
not need CORS headers during development.

## What the dashboard expects from the Go API

One GET endpoint per SQL file in `olap/queries`. Query parameters use the same
names as the SQL file headers. Filters left on "All" are simply not sent, so
the API should bind a missing parameter as `''` (the SQL already treats `''` as
"no filter").

| Endpoint | SQL file | Parameters the dashboard sends |
|---|---|---|
| `GET /api/reports/r1/category` | `r1_product_category_value/category.sql` | year, quarter, month, vehicle, size_group |
| `GET /api/reports/r1/product` | `r1_product_category_value/product.sql` | category, year, quarter, month, vehicle, size_group, top_n |
| `GET /api/reports/r2/pivot` | `r2_fleet_courier_workload/courier_vehicle_pivot.sql` | measure, year, quarter, month, courier, vehicle, age_band, size_group |
| `GET /api/reports/r2/cube` | `r2_fleet_courier_workload/courier_vehicle_cube.sql` | courier, year, quarter, month, vehicle, age_band, size_group |
| `GET /api/reports/r2/rider` | `r2_fleet_courier_workload/rider.sql` | courier, vehicle, year, quarter, month, age_band, sort, top_n |
| `GET /api/reports/r3/deciles` | `r3_customer_value_distribution/deciles.sql` | country, gender, year, quarter |
| `GET /api/reports/r3/geography` | `r3_customer_value_distribution/geography.sql` | level, country, gender, year, quarter, top_n |
| `GET /api/reports/r3/customer` | `r3_customer_value_distribution/customer.sql` | country, city, gender, decile, year, quarter, top_n |
| `GET /api/reports/r4/rollup` | `r4_demand_calendar/rollup.sql` | year, day_type, payday, vehicle, size_group |
| `GET /api/reports/r4/trend` | `r4_demand_calendar/trend.sql` | level, year, quarter, month, day_type, payday, vehicle, size_group |
| `GET /api/reports/r4/weekday_pivot` | `r4_demand_calendar/weekday_pivot.sql` | year, quarter, payday, vehicle, size_group |
| `GET /api/reports/r4/busiest_days` | `r4_demand_calendar/busiest_days.sql` | year, quarter, month, day_type, payday, vehicle, size_group, sort, top_n |

The API rejects a parameter a level does not declare, so the dashboard sends
each level only its own columns: the roll-up takes no quarter or month slice,
and the weekday pivot is already a month x weekday breakdown.

R3's `country` and `city` are drill state, never dropdown filters: `DIM_GEOGRAPHY`
holds ~240 countries and ~100,000 cities, so the dashboard only ever asks for the
one country or city the user clicked into.

**Response:** a JSON array of rows, or `{ "rows": [...] }`. Each row's keys are
the SQL output column names exactly (`value_share_pct`, `is_total`,
`grouping_level`, ...). Numbers may be JSON numbers or strings (Postgres
`NUMERIC` often arrives as a string); the dashboard converts them either way.

**Errors:** any non-2xx status. If the body is `{ "error": "message" }`, that
message is shown to the user.

## How the reports map to OLAP operations

| Report | Drill-down / roll-up | Slice | Dice | Pivot |
|---|---|---|---|---|
| R1 Products and categories | Click a category to drill to its products; click "All categories" in the route to roll back up | Year, quarter or month | Vehicle and order size together with the period | |
| R2 Fleet and rider workload | All couriers > courier > vehicle > riders; any grid cell jumps straight to those riders | Year, quarter or month | Courier, vehicle, rider age, order size | Courier x vehicle grid, switchable between total orders and orders per rider |
| R3 Customer value | Decile > its customers, and country > city > customers, as three peer views you can switch between | Year or quarter | Gender, together with whatever is drilled (a decile, a country, a city) | Decile value distribution: one bar per decile plus the running-total line |
| R4 Demand calendar | The whole date hierarchy in one table (month, its quarter, its year, the grand total); clicking a period opens the next finer grain in the trend view, and the route rolls the period back up | Year, quarter or month, on weekdays or weekends, on paydays or not | Vehicle and order size together with the period | Month x day-of-week grid of average orders per day, and the ROLLUP that returns every subtotal at once |

R3's deciles view draws the table's own numbers as a **Pareto chart**
(`src/components/ParetoChart.jsx`): one bar per decile plus the cumulative line,
on a single 0–100% scale so the line reaches the top gridline when the deciles
account for everything. The switch above the table (`Deciles` / `Geography` /
`Customers`) swaps peer views rather than drilling; the route line still shows
the drill state and rolls it back.

R4's four views are peers over one slice, so the same demand is read four ways:
the **roll-up** table, the **trend** line at a grain you choose (year, quarter,
month, week or day, with a 7-period moving average), the **weekday** pivot, and
**busiest days** (the day grain ranked, each day against the average day in the
same slice). `src/components/LineChart.jsx` draws the trend, `HeatCell` the
weekday pivot, and `CalendarGrid` one cell per day. At day grain the calendar
replaces the table and the chart sits under it: 365 table rows say less than a
calendar, and hovering a cell gives that day's exact figure.

Two things worth knowing when reading R4:

- **Demand is level.** The busiest weekday is 0.7% above the quietest and the
  busiest month 0.9% above the quietest, so the heat map and the bars read flat.
  That is the finding, not a broken colour scale: the network carries an even
  load all year.
- **A week that crosses a quarter boundary appears twice**, once for each
  quarter, because `trend.sql` groups weeks by year *and* quarter. `2024 W40` is
  a 1-day row (30 Sep) plus a 6-day row (1–6 Oct), each normalized to orders per
  day, so the two rows are still comparable.

Every table can be downloaded with **Export CSV** (the rows on screen, raw
numbers, column names as shown).

The route line above each table is the drill path. The amber stop is the
current level; clicking an earlier stop rolls up. Filters pinned by the drill
path (e.g. the courier you clicked into) are shown in amber and locked until
you zoom back out.

A **Legend** row under the scope sentence names what each mark means: bar
length (relative to the largest row on screen), heat-cell colour (darker means
more), the `–` glyph for no data, and the bold row for totals. The prose that
defines the measures themselves (list-price value, "busier than", orders per
rider) sits in the panel footer.

**Hovering a mark** — a bar, a heat cell, or a count such as units, riders or
days active — shows a tooltip with the exact reading: the full value, its
share, and how to act on it (e.g. "JNT · Motorcycle: 412,000 orders — click to
see these riders"). These are custom bubbles rendered in a
portal so they are not clipped by the table's scroll box; they also appear on
keyboard focus, and on a clickable row the remaining cells keep the native
"click to drill" hint. A column marks itself as `tip: true` in
`DataTable` when it draws its own tooltip, which is what keeps the two hints
from showing at once.

## Tests

Two suites run without a database or a browser, and CI runs both on every
change (`.github/workflows/dashboard-tests.yml`):

```bash
npm test                    # both suites, no warehouse needed
npm run sync:contracts      # regenerate the column contract from the API
npm run check:contracts     # diff columns and value types against the live API
```

**Column contracts** (`tests/contracts.test.mjs`). The sample data has to carry
exactly the columns each SQL file returns: mock mode is the default, so a
builder that drifts from its query shows a blank cell where live mode shows a
value. `src/api/contracts.js` pins that down — it is generated from
`GET /api/reports` and lists the columns of every path the dashboard can ask
for. The suite checks three things:

1. every sample row of every level carries exactly its query's columns;
2. no report reads a column its queries do not return;
3. every table column is a real column or derives its own value
   (`render` / `csv`).

`src/api/mock.js` also enforces (1) at runtime, so a drifting builder fails in
development rather than rendering a blank column. In a production build it logs
instead of throwing, so the demo still renders.

**Rendered reports** (`tests/report-markup.test.mjs`). The four reports are
rendered on the server in every view state — each R4 view and grain, pinned and
unpinned, both busiest-day sorts — and the markup is checked: row counts,
hierarchy indentation, columns, charts, the calendar, legends, notes,
breadcrumbs and figures. A case picks its view by replacing the component's
`useState` defaults with a read from `tests/support/reportState.js`, and its
data hook with `tests/support/useReport-mock.js`, which serves the sample rows
synchronously (bundled with `esbuild`). Where a claim is about a value — a
total, a busiest label, a deviation — the expectation is computed from the rows
that were rendered, so the suite checks the component's arithmetic instead of
restating a fixture. The patch list is asserted, so a renamed state literal
fails the build rather than silently testing the default view.

`npm run check:contracts` covers the one link CI cannot see — the SQL itself,
because the source archive is not in the repository, so CI cannot build the
warehouse. It compares the committed contract and the API's own column list
against what all 14 requestable paths return, and compares the value types of
the sample rows with the ones the warehouse sends (a NUMERIC that started
arriving as a string would slip past names alone). It writes
`evidence/contract-check.json` and exits non-zero on any difference. Run it
after changing a query, then `npm run sync:contracts` and extend the sample
builder for any column you added.

The SQL-to-catalog link runs in CI from the Go side as well:
`go test -tags integration ./internal/reports/` applies
`db/dw/init/01_dw_schema.sql` to a throwaway schema and prepares every query
against it, comparing the columns Postgres reports with the ones `catalog.go`
declares. Only the schema is needed, not the data.

## Folder layout

```
src/
  App.jsx                  sidebar + report header; the open report is in the URL hash (#r1..#r4)
  api/client.js            the only code that calls the API (mock or live)
  api/useReport.js         React hook: loads one report level, keeps old rows while reloading
  api/mock.js              sample rows shaped exactly like each SQL file's output
  api/contracts.js         generated: the columns each level returns (see Tests above)
  scripts/                 sync-contracts (regenerate the contract), check-contracts (diff it against the API)
  tests/                   column-contract and rendered-report suites (npm test)
  tests/support/           the test seam: initial view state, the mock data hook, the render entry
  components/              FilterBar, Panel, Figures (KPI cards), RoutePath (drill path), ScopeLine
                           (scope sentence), Legend (encoding key), Tooltip (hover hint), DataTable,
                           Bar, HeatCell (heat matrix cell), LineChart (time series), ParetoChart
                           (concentration), CalendarGrid (demand calendar), Segmented,
                           ExportButton, ReportStatus, Icons
  lib/csv.js               Export CSV
  lib/dimensions.js        filter options shared by all reports (values match the SQL)
  lib/format.js            peso / percent / count formatting
  reports/index.js         list of the four reports
  reports/ProductCategoryReport.jsx   R1
  reports/FleetWorkloadReport.jsx     R2
  reports/CustomerValueReport.jsx     R3
  reports/DemandCalendarReport.jsx    R4
  reports/ComingSoon.jsx              unused placeholder, kept as the starting point for a future report
```
