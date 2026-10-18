# Change notes — 2026-10-18

What changed after PR #15 (query optimizations) and PR #16 (functional tests),
and what each teammate needs to do. Three groups: the ETL pipeline now builds
the summary views itself, the dashboard was refined, and the status docs were
brought up to date.

## 1. The ETL pipeline builds the summary views

**Why.** Since PR #15 every report query reads the four materialized views
(`AGG_CUSTOMER_PERIOD`, `AGG_RIDER_DAY`, `AGG_CATEGORY_PERIOD`,
`AGG_PRODUCT_PERIOD`), and only `db/scripts/apply_optimizations.sh` created
them. Nothing ran it automatically and the setup steps did not mention it, so a
fresh clone, an `etl/run_etl.sh --rebuild` (the schema drops its tables with
`CASCADE`, which drops the views) or a new hosted server served no reports:
every one failed with "relation does not exist".

**What changed.** A new ETL phase, `--optimize` (`etl/load/summaries.py`), runs
after the load:

```
date → dims → facts → reconcile → optimize → check
```

| | `apply_optimizations.sh` (still works) | `--optimize` phase |
|---|---|---|
| Runs | by hand | automatically in every `run_etl.sh` / `--rebuild`, or `etl/main.py --optimize` |
| Reaches the database | `docker cp` + `psql` into the `stadvdb-mco1-dw-db` container | the ETL's own connection (`DW_*` settings), so a hosted database works too |
| On failure | each file runs separately | all three files in one transaction: everything or nothing |
| Checks | prints the sanity row | the same six view-versus-facts checks, and stops if any fails |
| Database name | `dw_db` | whatever the connection points at |

The SQL is unchanged: the phase runs the same three files in
`db/dw/optimize/` (dropping only psql's `\timing` lines). The resulting
warehouse is identical (the rebuilt views have the same row counts: 383,024 /
145,825 / 936 / 755,042), so **the benchmark in `evidence/optimization-log.md`
stays valid and does not need re-running.**

**Tests.** `etl/tests/test_summaries.py` (5, DB-free; the pipeline CI runs
them): the files run in order and commit, a failing check rolls everything back,
the settings target the connected database, and every view built is one the
report queries read. A new `test_run_ledger.py` case records the phase, and
`test_run_pipeline.py` and `test_package_layout.py` cover it too. Run once against the real
warehouse: 6/6 checks, 7.5 s, then the API and the 74 functional tests passed.

**Still a manual step:** reloading facts alone with `etl/main.py --facts` leaves
the views holding the old numbers until `etl/main.py --optimize` runs.

## 2. The dashboard (`olap-frontend/`)

All frontend; the report queries and the API are unchanged. Details are in
`olap-frontend/README.md`.

- **Readings that match the data.** The R4 weekday pivot and the R2 courier x
  vehicle grid gain a Colour switch: against the row's own average (blue
  above, orange below, full colour at 10% or more) or across the table. R3's
  customer average and R2's rider figures are labelled as covering only the
  rows listed, since those queries return the top N.
- **New and clearer charts.** A rider dot strip on R2 (each rider around the
  median, a ±5% "even share" band, a fixed ±10% axis so a small spread reads
  small); an 80% line and a running-total explanation on the R3 decile chart;
  round axis ticks on the R4 trend; ▲/▼ on R4's signed columns.
- **Tables.** Sortable headers on the flat tables (totals pinned, hierarchies
  left in order); dotted-underlined headers that explain the less obvious
  columns, worded from each query; R4's day-grain table back, closed under the
  calendar.
- **Access.** Charts read from the keyboard (arrow keys) and by touch; readout
  bubbles stay on screen; a light/dark switch at the bottom of the sidebar
  (follows the system until chosen); the light theme's muted grey now meets
  WCAG AA (4.70:1 at the lowest).
- **Fixes.** The R2 riders tooltip showed "– has 34 riders"; the chart hover
  picked a slightly wrong point near the edges.
- **Docker.** The `web` service sets `VITE_POLL=true`, because bind mounts on
  macOS and Windows pass no file events: edits now reach the browser without a
  restart.
- **Tests.** `npm test` is 407 checks (from 234): all four reports rendered
  across their views (R1–R3 in the new `olap-frontend/tests/report-views.test.mjs`), plus the
  table sort, the chart keyboard and pointer handling, and the theme's contrast
  and dark tokens.

Commits `6900890` to `f4c76d4` on `main`.

## 3. Status docs

`docs/project-checklist.md`, the main `README.md` status section and
`docs/technical-documentation/index.md` now record Steps 5 and 6 as done with
their evidence (`olap/tests/`, `evidence/functional-tests/`,
`evidence/optimization-log.md`). The final technical report is tracked
separately, so Step 7 left the checklist. The query READMEs and the
optimization log (a dated note; the analysis is untouched) now say the pipeline
builds the views.

Every suite was re-run on 2026-10-18 and passed: functional 74/74, Go 11/11,
ETL 198 (+19 that need `dw_test`, run in CI), importer 33/33, dashboard 407/407,
and the dashboard's contract check on all 14 levels.

## What each teammate needs to do

- **After pulling:** if your warehouse has no `AGG_*` views (you never ran
  `apply_optimizations.sh` after PR #15, so the dashboard shows errors), run
  once: `uv run --project etl python etl/main.py --optimize`. Otherwise nothing.
- **Docker:** recreate the dashboard container once to pick up `VITE_POLL`:
  `docker compose --profile app up -d web`.
- **Hosting:** run the ETL pipeline as usual; it now builds the views. Serve the
  built dashboard (`npm run build`) rather than the dev server, and set
  `CORS_ORIGINS` if the dashboard and the API end up on different addresses.
  Check each report on the hosted URL once.
