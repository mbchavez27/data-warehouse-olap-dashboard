# OLAP dashboard (React)

The web dashboard for the four warehouse reports. Built with React 18 and Vite,
no UI, chart or icon libraries: the tables, bars, pivot heat map and icons are
plain components so every part is easy to explain in the demo.

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

R4 follows the same shape, e.g. `/api/reports/r4/trend`.

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

R3's deciles view draws the table's own numbers as a **Pareto chart**
(`src/components/ParetoChart.jsx`): one bar per decile plus the cumulative line,
on a single 0–100% scale so the line reaches the top gridline when the deciles
account for everything. The switch above the table (`Deciles` / `Geography` /
`Customers`) swaps peer views rather than drilling; the route line still shows
the drill state and rolls it back.

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

## Folder layout

```
src/
  App.jsx                  sidebar + report header; the open report is in the URL hash (#r1, #r2)
  api/client.js            the only code that calls the API (mock or live)
  api/useReport.js         React hook: loads one report level, keeps old rows while reloading
  api/mock.js              sample rows shaped exactly like each SQL file's output
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
  reports/ComingSoon.jsx              placeholder for R4
```

## Adding R4

1. Copy `ProductCategoryReport.jsx` or `CustomerValueReport.jsx` as a starting
   point and point `useReport` at the new report and level names
   (`useReport('r4', 'trend', params)`).
2. Add a sample-data function for each level to `src/api/mock.js` and register
   it in `LEVELS`, returning the same columns as the SQL file.
3. Swap `ComingSoon` for the new component in `src/reports/index.js`.
