import { useState } from 'react'
import { useReport } from '../api/useReport.js'
import FilterBar from '../components/FilterBar.jsx'
import RoutePath from '../components/RoutePath.jsx'
import DataTable from '../components/DataTable.jsx'
import Bar from '../components/Bar.jsx'
import Legend from '../components/Legend.jsx'
import Tooltip from '../components/Tooltip.jsx'
import Figures from '../components/Figures.jsx'
import Segmented from '../components/Segmented.jsx'
import ReportStatus from '../components/ReportStatus.jsx'
import ScopeLine from '../components/ScopeLine.jsx'
import Panel from '../components/Panel.jsx'
import ExportButton from '../components/ExportButton.jsx'
import ParetoChart from '../components/ParetoChart.jsx'
import { YEAR, QUARTER, GENDER, emptyFilters, changeFilter } from '../lib/dimensions.js'
import { num, peso, pesoFull, pct, compact } from '../lib/format.js'
import { downloadCsv, slug } from '../lib/csv.js'

// R3 Customer Value Distribution
//   Deciles   -> olap/queries/r3_customer_value_distribution/deciles.sql
//   Geography -> olap/queries/r3_customer_value_distribution/geography.sql
//   Customers -> olap/queries/r3_customer_value_distribution/customer.sql
// Three peer views of one slice rather than a single straight drill: how
// concentrated value is, where the customers are, and who they are. Drilling
// (a decile, a country, a city) just narrows the slice, and the breadcrumb
// rolls that back. Country and city are drill state, never dropdown filters:
// DIM_GEOGRAPHY holds ~240 countries and ~100,000 cities.

const FILTERS = [YEAR, QUARTER, GENDER]
const FILTER_KEYS = FILTERS.map((f) => f.key)
const SCOPE_KEYS = [...FILTER_KEYS, 'country', 'city', 'decile']
const DRILL_ORDER = ['decile', 'country', 'city']
const VIEWS = [
  { value: 'deciles', label: 'Deciles' },
  { value: 'geography', label: 'Geography' },
  { value: 'customer', label: 'Customers' },
]
const TOP_N = [
  { value: '10', label: 'Top 10' },
  { value: '20', label: 'Top 20' },
  { value: '50', label: 'Top 50' },
]
const GENDER_NAMES = { All: 'All', F: 'Female', M: 'Male' }
const genderName = (g) => GENDER_NAMES[g] ?? g
const shareOf = (value, whole) => (whole ? (100 * Number(value)) / Number(whole) : null)

export default function CustomerValueReport() {
  const [filters, setFilters] = useState(() => emptyFilters(FILTERS))
  const [view, setView] = useState('deciles')
  const [geoLevel, setGeoLevel] = useState('country')
  const [drill, setDrill] = useState({ decile: null, country: null, city: null })
  const [topN, setTopN] = useState('20')

  // One level per view; each level reads only the drill state it understands.
  const country = geoLevel === 'city' || view === 'customer' ? drill.country : null
  let params
  if (view === 'geography') params = { ...filters, level: geoLevel, country: geoLevel === 'city' ? drill.country || '' : '', top_n: topN }
  else if (view === 'customer') params = { ...filters, country: drill.country || '', city: drill.city || '', decile: drill.decile || '', top_n: topN }
  else params = { ...filters }
  const { rows, loading, error, retry } = useReport('r3', view, params)

  // ---- drill path ----
  const path =
    view === 'geography'
      ? [{ label: 'All countries' }, ...(country ? [{ label: country, key: 'country' }] : [])]
      : [
          { label: 'All customers' },
          ...(view === 'customer' && drill.decile ? [{ label: `Value decile ${drill.decile}`, key: 'decile' }] : []),
          ...(view === 'customer' && drill.country ? [{ label: drill.country, key: 'country' }] : []),
          ...(view === 'customer' && drill.city ? [{ label: drill.city, key: 'city' }] : []),
        ]
  const zoomOut = (i) => {
    if (i === 0) {
      setDrill({ decile: null, country: null, city: null })
      setGeoLevel('country')
      return
    }
    const from = DRILL_ORDER.indexOf(path[i].key)
    setDrill((d) => ({ ...d, ...Object.fromEntries(DRILL_ORDER.slice(from).map((k) => [k, null])) }))
    if (path[i].key === 'country') setGeoLevel('country')
  }

  // ---- per-view content ----
  let figures = []
  let columns = []
  let table = {}
  let legend = []
  let chart = null
  let note = null
  let empty = false
  let exportName = 'r3.csv'

  if (view === 'deciles') {
    const customers = rows.reduce((s, r) => s + (Number(r.customers) || 0), 0)
    const value = rows.reduce((s, r) => s + (Number(r.value) || 0), 0)
    const maxValue = Math.max(0, ...rows.map((r) => Number(r.value) || 0))
    const top = rows[0]
    empty = !loading && !error && rows.length === 0

    figures = [
      { label: 'Customers', value: compact(customers), title: num(customers) },
      { label: 'List-price value', value: peso(value), title: pesoFull(value) },
      {
        label: 'Top decile holds',
        value: pct(top?.value_share_pct),
        sub: 'of list-price value, from the top 10% of customers',
      },
    ]
    chart = (
      <ParetoChart
        title="Share of list-price value by decile"
        labels={rows.map((r) => String(r.decile))}
        values={rows.map((r) => Number(r.value_share_pct) || 0)}
        cumulative={rows.map((r) => Number(r.cumulative_share_pct) || 0)}
        format={pct}
        max={100}
        barName="Share of value"
        lineName="Running total"
        lineHint="the share of value held by decile 1 through that decile, so it ends at 100%"
        reference={80}
        referenceName="80% of value"
      />
    )
    columns = [
      { key: 'decile', label: 'Decile', hint: 'Customers sorted by value and cut into ten equal groups; 1 is the top 10%', render: (r) => <span className="cell-strong">{r.decile}</span> },
      { key: 'customers', label: 'Customers', align: 'right', render: (r) => num(r.customers) },
      {
        key: 'value',
        label: 'List-price value',
        tip: true,
        hint: "Units times each product's current list price. The source keeps no price history, so read it as basket value, not revenue",
        render: (r) => (
          <Tooltip text={`${pesoFull(r.value)} — ${pct(r.value_share_pct)} of list-price value`}>
            <Bar value={Number(r.value)} max={maxValue}>
              {peso(r.value)}
            </Bar>
          </Tooltip>
        ),
      },
      { key: 'value_share_pct', label: 'Share of value', align: 'right', hint: "This decile's share of all customers' list-price value", render: (r) => pct(r.value_share_pct) },
      { key: 'cumulative_share_pct', label: 'Running total', align: 'right', hint: 'The share of value held by decile 1 through this one', render: (r) => pct(r.cumulative_share_pct) },
      {
        key: 'avg_value_per_customer',
        label: 'Average per customer',
        hint: "The decile's value divided by its customers",
        align: 'right',
        tip: true,
        render: (r) => (
          <Tooltip text={`${pesoFull(r.avg_value_per_customer)} on average, across ${num(r.customers)} customers`}>
            {peso(r.avg_value_per_customer)}
          </Tooltip>
        ),
      },
      {
        key: 'max_customer_value',
        label: 'Largest customer',
        hint: "The highest-value customer in this decile; hover a cell for the decile's range",
        align: 'right',
        tip: true,
        render: (r) => (
          <Tooltip
            text={`This decile runs from ${pesoFull(r.min_customer_value)} to ${pesoFull(r.max_customer_value)} of list-price value`}
          >
            {peso(r.max_customer_value)}
          </Tooltip>
        ),
      },
    ]
    table = {
      caption: 'Customer value by decile',
      rowKey: (r) => r.decile,
      onRowClick: (r) => {
        setDrill((d) => ({ ...d, decile: r.decile }))
        setView('customer')
      },
      drillHint: 'Show these customers',
      sortable: true,
    }
    legend = [{ swatch: 'bar', label: 'Bar length = list-price value, relative to the top decile' }]
    note =
      'Decile 1 is the 10% of customers with the highest list-price value and decile 10 the lowest. The line is the running total, so it shows how few deciles cover most of the value. Click a decile to list the customers in it.'
    exportName = 'r3-value-deciles.csv'
  }

  if (view === 'geography') {
    const locations = rows.filter((r) => r.grouping_level === 1)
    const grand = rows.find((r) => r.grouping_level === 3)
    const leader = locations[0]
    const maxValue = Math.max(0, ...rows.map((r) => Number(r.value) || 0))
    empty = !loading && !error && locations.length === 0

    const open = (r) => {
      if (geoLevel === 'country') {
        setDrill((d) => ({ ...d, country: r.location, city: null }))
        setGeoLevel('city')
      } else {
        setDrill((d) => ({ ...d, city: r.location }))
        setView('customer')
      }
    }

    figures = [
      {
        label: `Leading ${geoLevel}`,
        value: leader?.location ?? '–',
        text: true,
        sub: leader ? `${pct(shareOf(leader.value, grand?.value))} of list-price value` : null,
      },
      { label: 'Customers', value: compact(grand?.customers), title: num(grand?.customers) },
      { label: 'List-price value', value: peso(grand?.value), title: pesoFull(grand?.value) },
    ]
    columns = [
      {
        key: 'location',
        label: geoLevel === 'city' ? 'City' : 'Country',
        render: (r) => {
          // A location's gender rows read as children: the name sits on the total above them.
          if (r.grouping_level === 0) return ''
          if (r.grouping_level === 1) {
            return (
              <button type="button" className="link-cell" onClick={() => open(r)}>
                {r.location}
              </button>
            )
          }
          return <span className="cell-strong">{r.location}</span>
        },
        csv: (r) => r.location,
      },
      { key: 'gender', label: 'Gender', render: (r) => genderName(r.gender), csv: (r) => r.gender },
      { key: 'customers', label: 'Customers', align: 'right', render: (r) => num(r.customers) },
      { key: 'orders', label: 'Orders', align: 'right', render: (r) => num(r.orders) },
      {
        key: 'value',
        label: 'List-price value',
        tip: true,
        hint: "Units times each product's current list price. The source keeps no price history, so read it as basket value, not revenue",
        render: (r) => (
          <Tooltip text={`${pesoFull(r.value)} — ${peso(r.value_per_customer)} per customer`}>
            <Bar value={Number(r.value)} max={maxValue} track={r.grouping_level === 0}>
              {peso(r.value)}
            </Bar>
          </Tooltip>
        ),
      },
      {
        key: 'value_per_customer',
        label: 'Value per customer',
        hint: "The row's list-price value divided by its customers",
        align: 'right',
        render: (r) => peso(r.value_per_customer),
      },
      {
        key: 'value_rank',
        label: 'Rank',
        hint: 'Rank by value among rows of the same kind: locations among locations, gender splits among gender splits',
        align: 'right',
        render: (r) => (r.grouping_level >= 2 ? '' : r.value_rank),
      },
    ]
    table = {
      caption: `Customers and value by ${geoLevel}`,
      rowKey: (r, i) => `${r.location}-${r.gender}-${i}`,
      isTotal: (r) => r.grouping_level >= 1,
    }
    legend = [
      { swatch: 'bar', label: 'Bar length = list-price value, relative to the largest row shown' },
      { swatch: 'total', label: 'Bold rows = the location totals, the gender split and the grand total' },
    ]
    note =
      geoLevel === 'country'
        ? `Each country is followed by its customer gender split, showing only the genders present. The bold "All locations" rows cover every country, not only the ones listed. Click a country to break it into its cities.`
        : `Cities in ${drill.country} are followed by their gender split, again only the genders present. City is a fine grain, so most places hold one or two customers; the bold "All locations" row is the whole country. Click a city to list the customers in it.`
    exportName = geoLevel === 'city' ? `r3-cities-${slug(drill.country || 'all')}.csv` : 'r3-countries.csv'
  }

  if (view === 'customer') {
    const value = rows.reduce((s, r) => s + (Number(r.value) || 0), 0)
    const maxValue = Math.max(0, ...rows.map((r) => Number(r.value) || 0))
    const average = rows.length ? value / rows.length : null
    const top = rows[0]
    empty = !loading && !error && rows.length === 0

    figures = [
      { label: 'Customers listed', value: num(rows.length) },
      // Only the top N rows come back, so this is the average of those, not of every customer in the slice.
      {
        label: 'Average of those listed',
        value: peso(average),
        title: pesoFull(average),
        sub: rows.length ? `across the top ${num(rows.length)} by list-price value` : null,
      },
      {
        label: 'Top customer',
        value: top?.customer ?? '–',
        text: true,
        sub: top ? `${peso(top.value)} list-price value` : null,
      },
    ]
    columns = [
      { key: 'value_rank', label: 'Rank', align: 'right', hint: '1 = the highest-value customer in this selection, not only those listed' },
      { key: 'customer', label: 'Customer', hint: "The customer's username: the source's stable identifier, since the names are synthetic", render: (r) => <span className="cell-strong">{r.customer}</span> },
      ...(drill.country ? [] : [{ key: 'country', label: 'Country' }]),
      ...(drill.city ? [] : [{ key: 'city', label: 'City' }]),
      ...(filters.gender
        ? []
        : [{ key: 'gender', label: 'Gender', render: (r) => genderName(r.gender), csv: (r) => r.gender }]),
      { key: 'orders', label: 'Orders', align: 'right', render: (r) => num(r.orders) },
      { key: 'units', label: 'Units', align: 'right', render: (r) => num(r.units) },
      {
        key: 'value',
        label: 'List-price value',
        tip: true,
        hint: "Units times each product's current list price. The source keeps no price history, so read it as basket value, not revenue",
        render: (r) => (
          <Tooltip text={`${pesoFull(r.value)} — rank ${r.value_rank} by value in this selection`}>
            <Bar value={Number(r.value)} max={maxValue}>
              {peso(r.value)}
            </Bar>
          </Tooltip>
        ),
      },
      {
        key: 'avg_order_value',
        label: 'Average order',
        hint: "The customer's list-price value divided by their orders",
        align: 'right',
        render: (r) => peso(r.avg_order_value),
      },
      { key: 'decile', label: 'Decile', align: 'right', hint: 'Which tenth of this selection by value the customer falls in; 1 is the top 10%', render: (r) => r.decile },
      {
        key: 'value_percentile',
        label: 'Worth more than',
        hint: 'The share of customers in this selection with less list-price value than this one',
        align: 'right',
        render: (r) => `${pct(r.value_percentile)} of customers`,
      },
    ]
    table = {
      caption: drill.decile ? `Top customers in value decile ${drill.decile}` : 'Top customers by value',
      rowKey: (r) => `${r.customer}-${r.value_rank}`,
      sortable: true,
    }
    legend = [{ swatch: 'bar', label: 'Bar length = list-price value, relative to the top customer listed' }]
    note =
      'Usernames identify customers; the names in the source are synthetic, so the username is the stable identifier. "Worth more than" is a customer\'s position in the value ranking of this selection, and the decile is that same ranking in tenths.'
    exportName = `r3-customers-${slug(
      [drill.country, drill.city, drill.decile && `decile-${drill.decile}`].filter(Boolean).join(' ') || 'all',
    )}.csv`
  }

  return (
    <div className="report">
      <FilterBar
        defs={FILTERS}
        values={filters}
        onChange={(key, value) => setFilters((f) => changeFilter(f, key, value))}
        onClear={() => setFilters(emptyFilters(FILTERS))}
      />

      {!error && !empty && <Figures items={figures} />}

      <Panel
        loading={loading}
        title={<RoutePath stops={path} onSelect={zoomOut} />}
        actions={
          <>
            <Segmented label="View" options={VIEWS} value={view} onChange={setView} />
            {view !== 'deciles' && <Segmented label="Show" options={TOP_N} value={topN} onChange={setTopN} />}
            <ExportButton
              onClick={() => downloadCsv(exportName, columns, rows)}
              disabled={loading || !!error || empty}
            />
          </>
        }
        subheader={
          <ScopeLine
            noun="customers"
            keys={SCOPE_KEYS}
            values={
              view === 'geography'
                ? { ...filters, country: geoLevel === 'city' ? drill.country : null }
                : view === 'customer'
                  ? { ...filters, country: drill.country, city: drill.city, decile: drill.decile }
                  : filters
            }
          />
        }
        legend={!error && !empty ? <Legend items={legend} /> : null}
        footer={!error && !empty && note}
      >
        <ReportStatus loading={loading} error={error} empty={empty} onRetry={retry} />
        {!error && !empty && chart && <div className="panel-chart">{chart}</div>}
        {!error && !empty && <DataTable columns={columns} rows={rows} {...table} />}
      </Panel>
    </div>
  )
}
