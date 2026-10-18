import { useState } from 'react'
import { useReport } from '../api/useReport.js'
import FilterBar from '../components/FilterBar.jsx'
import RoutePath from '../components/RoutePath.jsx'
import DataTable from '../components/DataTable.jsx'
import Bar from '../components/Bar.jsx'
import HeatCell, { FULL_DEVIATION_PCT, deviationStrength } from '../components/HeatCell.jsx'
import Legend from '../components/Legend.jsx'
import Tooltip from '../components/Tooltip.jsx'
import Figures from '../components/Figures.jsx'
import Segmented from '../components/Segmented.jsx'
import ReportStatus from '../components/ReportStatus.jsx'
import ScopeLine from '../components/ScopeLine.jsx'
import Panel from '../components/Panel.jsx'
import ExportButton from '../components/ExportButton.jsx'
import LineChart from '../components/LineChart.jsx'
import CalendarGrid from '../components/CalendarGrid.jsx'
import {
  YEAR, QUARTER, MONTH, DAY_TYPE, PAYDAY, VEHICLE, SIZE_GROUP,
  emptyFilters, changeFilter, monthLabel,
} from '../lib/dimensions.js'
import { num, dec1, pct, compact } from '../lib/format.js'
import { downloadCsv } from '../lib/csv.js'

// R4 Demand Calendar
//   Roll-up      -> olap/queries/r4_demand_calendar/rollup.sql
//   Trend        -> olap/queries/r4_demand_calendar/trend.sql
//   Weekday      -> olap/queries/r4_demand_calendar/weekday_pivot.sql
//   Busiest days -> olap/queries/r4_demand_calendar/busiest_days.sql
// Four peer views of one slice: the date hierarchy rolled up at once; the same
// series at a chosen grain; the month x weekday pivot; and the day grain
// ranked. Clicking a roll-up row drills into that period in the trend view,
// and the breadcrumb rolls the period back up.

const ALL_FILTERS = [YEAR, QUARTER, MONTH, DAY_TYPE, PAYDAY, VEHICLE, SIZE_GROUP]
// Each level slices on what its SQL accepts: the roll-up has no quarter or
// month parameter, and the weekday pivot is already a month x weekday
// breakdown, so neither applies to it.
const VIEW_FILTERS = {
  rollup: [YEAR, DAY_TYPE, PAYDAY, VEHICLE, SIZE_GROUP],
  trend: ALL_FILTERS,
  weekday: [YEAR, QUARTER, PAYDAY, VEHICLE, SIZE_GROUP],
  busiest: ALL_FILTERS,
}
const LEVEL_BY_VIEW = { rollup: 'rollup', trend: 'trend', weekday: 'weekday_pivot', busiest: 'busiest_days' }
const PERIOD_KEYS = ['year', 'quarter', 'month']
const VIEWS = [
  { value: 'rollup', label: 'Roll-up' },
  { value: 'trend', label: 'Trend' },
  { value: 'weekday', label: 'Weekday' },
  { value: 'busiest', label: 'Busiest days' },
]
const GRAINS = [
  { value: 'year', label: 'Year' },
  { value: 'quarter', label: 'Quarter' },
  { value: 'month', label: 'Month' },
  { value: 'week', label: 'Week' },
  { value: 'day', label: 'Day' },
]
const MEASURES = [
  { value: 'per_day', label: 'Orders per day' },
  { value: 'orders', label: 'Total orders' },
]
// Weekday pivot colouring: each cell against its own month's average (the
// weekday pattern inside a month), or against the busiest cell in the table
// (which months and weekdays carried the most overall).
const COLOURS = [
  { value: 'within', label: 'Against its month' },
  { value: 'across', label: 'Across months' },
]
const SORTS = [
  { value: 'busiest', label: 'Busiest first' },
  { value: 'quietest', label: 'Quietest first' },
]
const TOP_N = [
  { value: '10', label: 'Top 10' },
  { value: '20', label: 'Top 20' },
  { value: '50', label: 'Top 50' },
]
const WEEKDAYS = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']]
const WEEKDAY_NAMES = {
  mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
}
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2025-03-14" -> "14 Mar 2025". The API sends a plain date, so no Date parsing.
function dayLabel(date) {
  const [year, month, day] = String(date).slice(0, 10).split('-')
  return `${Number(day)} ${MONTH_ABBR[Number(month) - 1]} ${year}`
}

const signed = (v) => (v === null || v === undefined || v === '' ? '–' : `${Number(v) > 0 ? '+' : ''}${pct(v)}`)

// A signed % for a table cell, with an arrow so ups and downs scan at a glance.
// The arrow is decoration; the sign already carries the meaning for a reader.
function Change({ value }) {
  if (value === null || value === undefined || value === '') return '–'
  const v = Number(value)
  if (!v) return signed(value)
  return (
    <span className={`change ${v > 0 ? 'is-up' : 'is-down'}`}>
      <span aria-hidden="true">{v > 0 ? '▲' : '▼'}</span>
      {` ${signed(value)}`}
    </span>
  )
}

// Names the filters a level ignores, so a value left over from another view
// never looks applied.
function notApplied(filters, names) {
  const off = names.filter(([key]) => filters[key]).map(([, label]) => label)
  if (!off.length) return ''
  return ` The ${off.join(' and ')} filter${off.length > 1 ? 's do' : ' does'} not apply at this level.`
}

export default function DemandCalendarReport() {
  const [filters, setFilters] = useState(() => emptyFilters(ALL_FILTERS))
  const [view, setView] = useState('rollup')
  const [grain, setGrain] = useState('month')
  const [measure, setMeasure] = useState('per_day')
  const [colour, setColour] = useState('within')
  const [sort, setSort] = useState('busiest')
  const [topN, setTopN] = useState('10')

  // Only the keys this level accepts reach the API.
  const activeFilters = VIEW_FILTERS[view]
  const keys = activeFilters.map((f) => f.key)
  const applied = Object.fromEntries(keys.map((k) => [k, filters[k]]))
  let params
  if (view === 'trend') params = { ...applied, level: grain }
  else if (view === 'busiest') params = { ...applied, sort, top_n: topN }
  else params = applied
  const { rows, loading, error } = useReport('r4', LEVEL_BY_VIEW[view], params)

  // ---- drill path: the period filters, read back as the date hierarchy ----
  const path = [{ label: 'All dates' }]
  if (keys.includes('year') && filters.year) path.push({ label: filters.year, key: 'year' })
  if (keys.includes('quarter') && filters.quarter) path.push({ label: `Q${filters.quarter}`, key: 'quarter' })
  if (keys.includes('month') && filters.month) {
    path.push({ label: `${monthLabel(filters.month)}${filters.year ? ` ${filters.year}` : ''}`, key: 'month' })
  }
  const zoomOut = (i) => {
    const from = i === 0 ? 0 : PERIOD_KEYS.indexOf(path[i].key) + 1
    setFilters((f) => ({ ...f, ...Object.fromEntries(PERIOD_KEYS.slice(from).map((k) => [k, ''])) }))
  }

  // ---- per-view content ----
  let figures = []
  let columns = []
  let table = {}
  let legend = []
  let chart = null
  let calendar = null
  let showTable = true
  let note = null
  let empty = false
  let exportName = 'r4.csv'

  if (view === 'rollup') {
    const grand = rows.find((r) => r.hierarchy_level === 'all')
    const months = rows.filter((r) => r.hierarchy_level === 'month')
    const busiest = months.reduce((a, b) => (!a || Number(b.orders_per_day) > Number(a.orders_per_day) ? b : a), null)
    const quietest = months.reduce((a, b) => (!a || Number(b.orders_per_day) < Number(a.orders_per_day) ? b : a), null)
    const spread =
      busiest && quietest && Number(quietest.orders_per_day)
        ? (100 * (Number(busiest.orders_per_day) - Number(quietest.orders_per_day))) / Number(quietest.orders_per_day)
        : null
    const total = Number(grand?.orders) || 0
    empty = !loading && !error && !rows.length

    const period = (r) =>
      r.hierarchy_level === 'all'
        ? 'All dates'
        : r.hierarchy_level === 'year'
          ? String(r.year)
          : r.hierarchy_level === 'quarter'
            ? `Q${r.quarter} ${r.year}`
            : `${r.month_name} ${r.year}`
    const open = (r) => {
      // Drilling sets the period filters and opens the next finer grain.
      setFilters((f) => ({
        ...f,
        year: r.year === null ? '' : String(r.year),
        quarter: r.quarter === null ? '' : String(r.quarter),
        month: r.month === null ? '' : String(r.month),
      }))
      setGrain(r.hierarchy_level === 'year' ? 'quarter' : r.hierarchy_level === 'quarter' ? 'month' : 'day')
      setView('trend')
    }

    figures = [
      { label: 'Orders delivered', value: compact(grand?.orders), title: num(grand?.orders) },
      { label: 'Orders per day', value: dec1(grand?.orders_per_day) },
      {
        label: 'Busiest month over the quietest',
        value: spread === null ? '–' : `+${dec1(spread)}%`,
        sub:
          busiest && quietest
            ? `${busiest.month_name} ${busiest.year} against ${quietest.month_name} ${quietest.year}`
            : null,
      },
    ]
    columns = [
      {
        key: 'period',
        label: 'Period',
        render: (r) => (
          <span
            className={
              r.hierarchy_level === 'year' || r.hierarchy_level === 'all'
                ? 'cell-strong'
                : `cell-strong hier-${r.hierarchy_level === 'quarter' ? 1 : 2}`
            }
          >
            {period(r)}
          </span>
        ),
        csv: period,
      },
      { key: 'days', label: 'Days', align: 'right', render: (r) => num(r.days) },
      { key: 'orders', label: 'Orders', align: 'right', render: (r) => num(r.orders) },
      { key: 'orders_per_day', label: 'Orders per day', align: 'right', render: (r) => dec1(r.orders_per_day) },
      { key: 'units', label: 'Units', align: 'right', render: (r) => num(r.units) },
      {
        key: 'order_share',
        label: 'Share of orders',
        align: 'right',
        render: (r) => pct(total ? (100 * Number(r.orders)) / total : null),
        csv: (r) => (total ? Math.round((1000 * Number(r.orders)) / total) / 10 : ''),
      },
    ]
    table = {
      caption: 'Orders by month, quarter and year',
      rowKey: (r) => `${r.hierarchy_level}-${r.year}-${r.quarter}-${r.month}`,
      onRowClick: open,
      canDrill: (r) => r.hierarchy_level !== 'all',
      isTotal: (r) => r.hierarchy_level === 'all',
      drillHint: 'Open this period in the trend view',
    }
    legend = [{ swatch: 'total', label: 'Bold rows = the quarter, year and overall subtotals' }]
    note = `Every month, its quarter subtotal, its year subtotal and the grand total in one result, each normalized to orders per day so the 7-day September 2024 compares with a full month. Click a period to open it in the trend view.${notApplied(
      filters,
      [['quarter', 'quarter'], ['month', 'month']],
    )}`
    exportName = 'r4-rollup.csv'
  }

  if (view === 'trend') {
    const maxOrders = Math.max(0, ...rows.map((r) => Number(r.orders) || 0))
    const busiest = rows.reduce((a, b) => (!a || Number(b.orders_per_day) > Number(a.orders_per_day) ? b : a), null)
    const quietest = rows.reduce((a, b) => (!a || Number(b.orders_per_day) < Number(a.orders_per_day) ? b : a), null)
    const gap =
      busiest && quietest && Number(quietest.orders_per_day)
        ? (100 * (Number(busiest.orders_per_day) - Number(quietest.orders_per_day))) / Number(quietest.orders_per_day)
        : null
    const perDay = measure === 'per_day'
    const showingAverage = perDay && rows.length > 7 // a 7-period window needs more than 7 periods
    empty = !loading && !error && !rows.length

    const label = (r) => (grain === 'day' ? dayLabel(r.period_label) : r.period_label)
    const series = [
      { name: perDay ? 'Orders per day' : 'Orders', values: rows.map((r) => Number(perDay ? r.orders_per_day : r.orders) || 0) },
    ]
    if (showingAverage) {
      series.push({ name: '7-period average', values: rows.map((r) => Number(r.moving_avg_orders_per_day) || 0), dashed: true })
    }
    chart = (
      <LineChart
        title={`${perDay ? 'Orders per day' : 'Orders'} by ${grain}`}
        labels={rows.map((r) => r.period_label)}
        series={series}
        format={perDay ? dec1 : num}
        axisFormat={num}
      />
    )
    if (grain === 'day') {
      calendar = (
        <CalendarGrid
          title="Orders per day"
          points={rows.map((r) => ({ date: r.period_start, value: Number(r.orders_per_day) || 0, label: dayLabel(r.period_label) }))}
          format={dec1}
        />
      )
    }

    figures = [
      {
        label: 'Busiest period',
        value: busiest ? label(busiest) : '–',
        text: true,
        sub: busiest ? `${dec1(busiest.orders_per_day)} orders per day` : null,
      },
      {
        label: 'Quietest period',
        value: quietest ? label(quietest) : '–',
        text: true,
        sub: quietest ? `${dec1(quietest.orders_per_day)} orders per day` : null,
      },
      {
        label: 'Busiest over the quietest',
        value: gap === null ? '–' : `+${dec1(gap)}%`,
        sub: `${num(rows.length)} periods of one ${grain} in this slice`,
      },
    ]
    columns = [
      { key: 'period_label', label: 'Period', render: (r) => <span className="cell-strong">{label(r)}</span>, csv: label },
      { key: 'days', label: 'Days', align: 'right', render: (r) => num(r.days) },
      {
        key: 'orders',
        label: 'Orders',
        tip: true,
        render: (r) => (
          <Tooltip
            text={`${num(r.orders)} orders over ${num(r.days)} ${r.days === 1 ? 'day' : 'days'} — ${dec1(
              r.orders_per_day,
            )} a day`}
          >
            <Bar value={Number(r.orders)} max={maxOrders}>
              {num(r.orders)}
            </Bar>
          </Tooltip>
        ),
      },
      { key: 'orders_per_day', label: 'Orders per day', align: 'right', render: (r) => dec1(r.orders_per_day) },
      {
        key: 'change_vs_previous_pct',
        label: 'Change vs previous',
        align: 'right',
        render: (r) => <Change value={r.change_vs_previous_pct} />,
        csv: (r) => (r.change_vs_previous_pct === null ? '' : r.change_vs_previous_pct),
      },
      {
        key: 'moving_avg_orders_per_day',
        label: '7-period average',
        align: 'right',
        render: (r) => dec1(r.moving_avg_orders_per_day),
      },
      { key: 'units', label: 'Units', align: 'right', render: (r) => num(r.units) },
    ]
    table = { caption: `Orders by ${grain}`, rowKey: (r) => `${r.period_label}-${r.period_start}` }
    showTable = grain !== 'day'
    legend = showTable
      ? [
          { swatch: 'bar', label: 'Bar length = orders, relative to the busiest period listed' },
          { swatch: 'glyph', glyph: '▲▼', label: 'Change vs previous: up or down on the period before' },
        ]
      : []
    note = `Each row is one ${grain}, and orders per day divides a period's orders by its calendar days, so the 7-day September 2024 and the 23-day September 2025 compare with full months.${
      showingAverage ? ' The dashed line is a 7-period moving average.' : ''
    }${
      grain === 'week' ? ' A week that crosses a quarter boundary appears once for each quarter, so 2024 W40 is a one-day row plus a six-day row.' : ''
    }${grain === 'day' ? ' At day grain the calendar above is the table: hover any cell for that day.' : ''}`
    exportName = `r4-trend-${grain}.csv`
  }

  if (view === 'weekday') {
    const months = rows.filter((r) => !r.is_total)
    const total = rows.find((r) => r.is_total)
    empty = !loading && !error && !rows.length
    const maxCell = Math.max(0, ...months.flatMap((r) => WEEKDAYS.map(([k]) => Number(r[k]) || 0)))
    // A cell's distance from its own row's average, in %.
    const deviationOf = (row, key) => {
      const value = row[key]
      const average = Number(row.all_days)
      return value === null || value === undefined || !average ? null : (100 * (Number(value) - average)) / average
    }
    const withinMonth = colour === 'within'

    const heat = (row, key, name) => {
      const value = row[key]
      const who = row.is_total ? 'All months together' : row.month_label
      const deviation = deviationOf(row, key)
      return (
        <HeatCell
          value={value}
          max={maxCell}
          strength={withinMonth ? deviationStrength(deviation) : undefined}
          below={withinMonth && deviation < 0}
          tip={`${who} · ${name}: ${num(value)} orders per day${
            deviation === null ? '' : ` — ${signed(deviation)} against that month's average`
          }`}
          emptyTip={`No deliveries in ${who} on a ${name}`}
        />
      )
    }

    const averagePerWeekday = total
      ? WEEKDAYS.map(([k]) => ({ name: WEEKDAY_NAMES[k], value: Number(total[k]) })).filter((x) => Number.isFinite(x.value))
      : []
    const ranked = [...averagePerWeekday].sort((a, b) => b.value - a.value)
    const busiestDay = ranked[0]
    const quietestDay = ranked[ranked.length - 1]
    const gap =
      busiestDay && quietestDay && quietestDay.value
        ? (100 * (busiestDay.value - quietestDay.value)) / quietestDay.value
        : null

    figures = [
      {
        label: 'Busiest weekday',
        value: busiestDay?.name ?? '–',
        text: true,
        sub: busiestDay ? `${dec1(busiestDay.value)} orders per day` : null,
      },
      {
        label: 'Quietest weekday',
        value: quietestDay?.name ?? '–',
        text: true,
        sub: quietestDay ? `${dec1(quietestDay.value)} orders per day` : null,
      },
      {
        label: 'Busiest over the quietest',
        value: gap === null ? '–' : `+${dec1(gap)}%`,
        sub: 'orders per day, over the whole period',
      },
    ]
    columns = [
      {
        key: 'month_label',
        label: 'Month',
        render: (r) => (r.is_total ? <span className="cell-strong">{r.month_label}</span> : r.month_label),
      },
      ...WEEKDAYS.map(([key, name]) => ({
        key,
        label: name,
        align: 'right',
        tip: true,
        render: (r) => heat(r, key, name),
      })),
      {
        key: 'all_days',
        label: 'All days',
        align: 'right',
        render: (r) => <span className="cell-strong">{dec1(r.all_days)}</span>,
      },
    ]
    table = { caption: 'Average orders per day by month and weekday', rowKey: (r) => r.month_label, isTotal: (r) => r.is_total }
    legend = [
      withinMonth
        ? { swatch: 'diverge', label: `Cell colour = against that month's average; blue busier, orange quieter, full colour at ${FULL_DEVIATION_PCT}% or more` }
        : { swatch: 'heat', label: 'Cell colour = orders per day; darker means busier' },
      { swatch: 'total', label: 'Bold row = every month together' },
      { swatch: 'glyph', glyph: '–', label: 'No deliveries in that month and weekday' },
    ]
    note = `Each cell is the average orders per day a month carried on that weekday, so 4-day and 5-day weekdays compare. ${
      withinMonth
        ? "Read the All days column for how full a month is and the cell colour for when inside it the orders landed: blue weekdays ran above that month's average, orange ones below, and pale cells sat close to it."
        : 'The colour scales every cell against the busiest one in the table, so it shows which months and weekdays carried the most orders overall. Switch to Against its month to see each month\'s own weekday pattern.'
    }${notApplied(
      filters,
      [['month', 'month'], ['day_type', 'day type']],
    )}`
    exportName = 'r4-weekday.csv'
  }

  if (view === 'busiest') {
    const top = rows[0]
    empty = !loading && !error && !rows.length

    figures = [
      {
        label: sort === 'busiest' ? 'Busiest day' : 'Quietest day',
        value: top ? dayLabel(top.date) : '–',
        text: true,
        sub: top ? `${num(top.orders)} orders, on a ${top.day_name}` : null,
      },
      {
        label: 'Versus the average day',
        value: top ? signed(top.vs_average_pct) : '–',
        sub: 'the average day across the whole slice',
      },
      { label: 'Orders per active rider', value: dec1(top?.orders_per_active_rider) },
    ]
    columns = [
      { key: 'demand_rank', label: 'Rank', align: 'right' },
      { key: 'date', label: 'Date', render: (r) => <span className="cell-strong">{dayLabel(r.date)}</span>, csv: (r) => r.date },
      {
        key: 'day_name',
        label: 'Day',
        render: (r) => (
          <>
            {r.day_name}
            {r.is_weekend && <span className="cell-muted"> · weekend</span>}
            {r.is_payday && <span className="cell-muted"> · payday</span>}
          </>
        ),
        csv: (r) => [r.day_name, r.is_weekend && 'weekend', r.is_payday && 'payday'].filter(Boolean).join(' · '),
      },
      { key: 'orders', label: 'Orders', align: 'right', render: (r) => num(r.orders) },
      {
        key: 'vs_average_pct',
        label: 'Versus the average day',
        align: 'right',
        render: (r) => <Change value={r.vs_average_pct} />,
        csv: (r) => (r.vs_average_pct === null ? '' : r.vs_average_pct),
      },
      { key: 'units', label: 'Units', align: 'right', render: (r) => num(r.units) },
      { key: 'active_riders', label: 'Riders', align: 'right', render: (r) => num(r.active_riders) },
      {
        key: 'orders_per_active_rider',
        label: 'Orders per rider',
        align: 'right',
        render: (r) => dec1(r.orders_per_active_rider),
      },
    ]
    table = { caption: sort === 'busiest' ? 'Busiest days' : 'Quietest days', rowKey: (r) => r.date }
    legend = [
      {
        swatch: 'glyph',
        glyph: '▲▼',
        label: 'That column compares a day with the average day in the same slice: above or below it',
      },
    ]
    note = `Ranked from every day in the slice, not only the rows shown. "Versus the average day" is each day's orders against the average day in the same slice, so +5% is how far a spike really rises above a level base. Weekend and payday days are marked next to the day name, because those are the days the calendar would flag.`
    exportName = `r4-busiest-days-${sort}.csv`
  }

  const actions = (
    <>
      <Segmented label="View" options={VIEWS} value={view} onChange={setView} />
      {view === 'trend' && <Segmented label="By" options={GRAINS} value={grain} onChange={setGrain} />}
      {view === 'trend' && <Segmented label="Show" options={MEASURES} value={measure} onChange={setMeasure} />}
      {view === 'weekday' && <Segmented label="Colour" options={COLOURS} value={colour} onChange={setColour} />}
      {view === 'busiest' && <Segmented label="Order" options={SORTS} value={sort} onChange={setSort} />}
      {view === 'busiest' && <Segmented label="Show" options={TOP_N} value={topN} onChange={setTopN} />}
      <ExportButton onClick={() => downloadCsv(exportName, columns, rows)} disabled={loading || !!error || empty} />
    </>
  )

  return (
    <div className="report">
      <FilterBar
        defs={activeFilters}
        values={filters}
        onChange={(key, value) => setFilters((f) => changeFilter(f, key, value))}
        onClear={() => setFilters(emptyFilters(ALL_FILTERS))}
      />

      {!error && !empty && <Figures items={figures} />}

      <Panel
        loading={loading}
        title={<RoutePath stops={path} onSelect={zoomOut} />}
        actions={actions}
        subheader={<ScopeLine keys={keys} values={filters} />}
        legend={!error && !empty && legend.length ? <Legend items={legend} /> : null}
        footer={!error && !empty && note}
      >
        <ReportStatus loading={loading} error={error} empty={empty} />
        {!error && !empty && calendar && <div className="panel-chart">{calendar}</div>}
        {!error && !empty && chart && <div className="panel-chart">{chart}</div>}
        {!error && !empty && showTable && <DataTable columns={columns} rows={rows} {...table} />}
      </Panel>
    </div>
  )
}
