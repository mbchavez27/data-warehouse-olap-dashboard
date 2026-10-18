# OLAP dashboard (React)

The web dashboard for the four warehouse reports. Built with React 18 and Vite,
no UI, chart or icon libraries: the tables, bars, pivot heat maps, line chart,
Pareto chart, dot strip, demand calendar and icons are plain components so every
part is easy to explain in the demo.

## Run it

The group runs the whole stack with Docker Compose from the repository root:

```bash
docker compose --profile app up -d
```

The `web` service serves the dashboard on http://localhost:3000 in live mode,
against the Go API and the warehouse. It also sets `VITE_POLL=true`: Docker bind
mounts on macOS and Windows pass no file-change events into the container, so
Vite polls the mounted files instead and an edit shows in the browser within a
few seconds. After pulling a change to `docker-compose.yml`, recreate the
container once with `docker compose --profile app up -d web`. The API reads its
SQL only at startup, so restart it (`docker compose --profile app restart api`)
after a query changes.

Without Docker:

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

## Home page

Opening the dashboard (no hash, or `#home`) shows the home page
(`src/Home.jsx`): the Road Runner title, the "Last-mile logistics analytics"
subtitle, what the dashboard covers and the data's date range, and a card per
report with the question it answers, a line on how to explore it (`explore` in
`src/reports/index.js`) and a link to open it. It requests no data, so each
report stays the only source of its numbers. The sidebar's Home link and the
logo return to it (`src/lib/route.js`).

## When something goes wrong

- **A link to a page that doesn't exist** (`#r9`, a typo, an old bookmark)
  opens a "Page not found" page (`src/NotFound.jsx`) naming the bad link, with
  links home and to each report, instead of silently opening a report.
- **A report that fails to load** shows what went wrong in its panel with a
  **Try again** button that re-sends the same request (`retry` from
  `src/api/useReport.js`). The messages are written for visitors: the API's own
  error text when it sends one, and "Couldn't reach the report service" when
  the network fails or the `/api` proxy answers an empty 5xx because the API is
  down or restarting (`src/api/client.js`).
- **A crash while rendering a page** is caught by `ErrorBoundary`, which shows
  a "Something went wrong" page with Reload and Home buttons and the technical
  details folded away, instead of a blank screen. The sidebar keeps working, and
  moving to another page clears the error.
- **No rows for the chosen filters** says so and suggests another period or
  clearing a filter.

The not-found and crash pages share `src/components/ErrorPage.jsx`.

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
account for everything. The chart's key says what the running total adds up, and
a dashed line marks 80% of value, so where the running total crosses it shows
how many deciles hold most of the value. The switch above the table (`Deciles` / `Geography` /
`Customers`) swaps peer views rather than drilling; the route line still shows
the drill state and rolls it back.

R4's four views are peers over one slice, so the same demand is read four ways:
the **roll-up** table, the **trend** line at a grain you choose (year, quarter,
month, week or day, with a 7-period moving average), the **weekday** pivot, and
**busiest days** (the day grain ranked, each day against the average day in the
same slice). `src/components/LineChart.jsx` draws the trend, `HeatCell` the
weekday pivot, and `CalendarGrid` one cell per day. At day grain the calendar
leads, the chart sits under it, and the daily table follows closed ("Show the
daily numbers as a table"): 365 rows say less than a calendar, but the table is
still there to read, sort, or reach from the keyboard. The trend's y-axis sits on
round values (0, 1,000, 2,000, ...), and "Change vs previous" and "Versus the
average day" carry a blue ▲ or orange ▼ so rises and dips scan at a glance.

The **weekday pivot** has a Colour switch. "Against its month" (the default)
colours each cell against that month's own average on a diverging scale, blue
above and orange below, reaching full colour at 10% or more; it shows when
inside a month the orders land. "Across months" colours every cell against the
busiest one in the table instead, which shows which months carried the most.

R2's **courier x vehicle grid** has the same switch: "Across couriers" (the
default) or "Against its courier", which colours each vehicle against that
courier's own average, i.e. whether its vehicles share the work evenly. At the
**rider** level a dot strip above the table plots each listed rider's orders
around the median, with a shaded band for within 5% of it. Its axis spans a
fixed ±10% of the median, so a small spread reads small instead of being
stretched to fill the chart, and the band, median and axis offsets are labelled
on the chart itself. Days active also shows the query's `utilization_pct`.

Two things worth knowing when reading R4:

- **Demand is level.** The busiest weekday is 0.7% above the quietest and the
  busiest month 0.9% above the quietest, so the weekday cells stay pale (well
  under the 10% that reaches full colour) and the bars read flat. That is the
  finding, not a broken colour scale: the network carries an even load all year.
  The same goes for R2's riders, who sit within a few percent of each other.
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
more, or blue above and orange below on the "against its average" scales), the
▲▼ arrows, the `–` glyph for no data, and the bold row for totals. The prose that
defines the measures themselves (list-price value, "busier than", orders per
rider) sits in the panel footer.

Figures describe what the query returned. A level that returns only the top N
rows says so ("Average of those listed", "across the 20 busiest riders") rather
than presenting an average of the listed rows as the whole population's.

**Column explanations.** The less obvious columns have a dotted-underlined
header; hovering or focusing it explains the column, worded from how its query
computes it (e.g. "Rank" and "Busier than" are worked out across the whole
selection, not only the rows listed). A `DataTable` column opts in with `hint`.

**Sorting.** Flat tables pass `sortable` to `DataTable`, which turns each header
into a button: numbers sort largest first and text A to Z, a second click
reverses, and a third restores the query's own order. Total rows stay pinned,
and the sort resets when a drill changes the level. Tables whose row order is a
hierarchy (the R4 roll-up, R3 geography) and the R4 weekday grid are not
sortable. A column can sort by something other than its label with `sortValue`
(R4 trend periods sort by start date).

**Hovering a mark** — a bar, a heat cell, or a count such as units, riders or
days active — shows a tooltip with the exact reading: the full value, its
share, and how to act on it (e.g. "JNT · Motorcycle: 412,000 orders — click to
see these riders"). These are custom bubbles rendered in a
portal so they are not clipped by the table's scroll box; they also appear on
keyboard focus, and on a clickable row the remaining cells keep the native
"click to drill" hint. A column marks itself as `tip: true` in
`DataTable` when it draws its own tooltip, which is what keeps the two hints
from showing at once.

**Charts work from the keyboard and by touch** (`src/lib/chartKeys.js`). Tab to
a chart and its first point's readout appears; the left and right arrow keys
step through the points, Home and End jump to the ends, and Escape hides it.
Each reading is also announced to screen readers. The charts use pointer events,
so a tap reads the nearest point (on the dot strip, the nearest dot), a sideways
drag scrubs while vertical swipes still scroll, and a touch reading stays until
you tap elsewhere. Readout bubbles stay inside the chart near its edges.

**Light and dark mode.** The switch at the bottom of the sidebar flips between
them. Until a viewer picks one, the page follows the system setting (and keeps
up if it changes); a choice is pinned with `data-theme` on `<html>` and
remembered in that browser (`src/lib/theme.js`), and a small script in
`index.html` applies it before the first paint so a dark page never flashes
light. Every colour in `src/styles.css` reads from a token on `:root`, and a dark
block redefines each one. Text meets WCAG AA contrast in both themes: the muted
grey (`--ink-3`) is at least 4.7:1 on every light background, and dark text is
4.97:1 at the lowest, on the strongest orange heat cell. Tests hold both.

## Tests

Three suites run without a database or a browser, and CI runs them on every
change (`.github/workflows/dashboard-tests.yml`):

```bash
npm test                    # all three suites, no warehouse needed
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

**Rendered reports** (`tests/report-markup.test.mjs` for R4,
`tests/report-views.test.mjs` for R1, R2 and R3). The four reports are rendered
on the server across their views and drill levels — each R4 view and grain,
pinned and unpinned, both busiest-day sorts and both weekday colourings; R1
categories and products; R2's grid in both colourings, one courier's vehicles
and the riders; R3's deciles, geography and a decile's customers — and the
markup is checked: row counts, hierarchy indentation, columns, charts, the
calendar, legends, notes, breadcrumbs, figures, sortable and explained headers,
and the keyboard-readable charts. The same files test the table sort order
(numbers sent as strings, pinned totals, blanks last), the chart keyboard and
pointer handling, and that the dark theme redefines every colour token. A case picks its view by replacing the component's
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
index.html                 page shell; applies a saved light/dark choice before the first paint
public/                    favicon
scripts/                   sync-contracts (regenerate the contract), check-contracts (diff it against the API)
tests/                     column-contract suite and the two rendered-report suites (npm test)
tests/support/             the test seam: initial view state, the mock data hook, the render entry
src/
  main.jsx                 mounts the app
  styles.css               every style, on light and dark colour tokens
  App.jsx                  sidebar + report header; the open page is in the URL hash (#home, #r1..#r4)
  Home.jsx                 home page: title, overview and a card per report
  NotFound.jsx             page for a link to a page that doesn't exist
  api/client.js            the only code that calls the API (mock or live)
  api/useReport.js         React hook: loads one report level, keeps old rows while reloading
  api/mock.js              sample rows shaped exactly like each SQL file's output
  api/contracts.js         generated: the columns each level returns (see Tests above)
  components/              FilterBar, Panel, Figures (KPI cards), RoutePath (drill path), ScopeLine
                           (scope sentence), Legend (encoding key), Tooltip (hover hint), DataTable,
                           Bar, HeatCell (heat matrix cell), LineChart (time series), ParetoChart
                           (concentration), DotStrip (spread around the median), CalendarGrid
                           (demand calendar), Segmented, ExportButton, ReportStatus,
                           ThemeToggle (light / dark switch), ErrorPage and ErrorBoundary
                           (not-found and crashed-page screens), Logo (the Road Runner mark), Icons
  lib/chartKeys.js         keyboard and pointer reading shared by the charts
  lib/theme.js             light / dark choice: system default, pinned and remembered
  lib/route.js             which page a URL hash opens: home, a report, or not found
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
