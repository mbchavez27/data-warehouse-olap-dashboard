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
import {
  YEAR, QUARTER, MONTH, COURIER, VEHICLE, AGE_BAND, SIZE_GROUP,
  emptyFilters, changeFilter,
} from '../lib/dimensions.js'
import { num, pct, dec1, compact } from '../lib/format.js'
import { downloadCsv, slug } from '../lib/csv.js'

// R2 Fleet, Courier & Rider Workload
//   Courier x vehicle grid -> courier_vehicle_pivot.sql
//   One courier's vehicles -> courier_vehicle_cube.sql (courier pinned)
//   Riders                 -> rider.sql (courier and/or vehicle pinned)
// Click a courier to drill into its vehicles, a vehicle to drill into its
// riders, or any grid cell to jump straight to those riders.

const FILTERS = [YEAR, QUARTER, MONTH, COURIER, VEHICLE, AGE_BAND, SIZE_GROUP]
const RIDER_FILTERS = FILTERS.filter((f) => f !== SIZE_GROUP) // rider.sql has no order-size filter
const VEHICLES = [
  ['motorcycle', 'Motorcycle'],
  ['bicycle', 'Bicycle'],
  ['car', 'Car'],
  ['trike', 'Trike'],
]
const MEASURES = [
  { value: 'orders', label: 'Total orders' },
  { value: 'per_rider', label: 'Orders per rider' },
]
const SORTS = [
  { value: 'most', label: 'Busiest first' },
  { value: 'least', label: 'Quietest first' },
]
const TOP_N = [
  { value: '10', label: 'Top 10' },
  { value: '20', label: 'Top 20' },
  { value: '100', label: 'All' },
]

export default function FleetWorkloadReport() {
  const [filters, setFilters] = useState(() => emptyFilters(FILTERS))
  const [drill, setDrill] = useState({ courier: null, vehicle: null })
  const [measure, setMeasure] = useState('orders')
  const [sort, setSort] = useState('most')
  const [topN, setTopN] = useState('20')

  const level = drill.vehicle ? 'rider' : drill.courier ? 'cube' : 'pivot'
  const courier = drill.courier || filters.courier
  const vehicle = drill.vehicle || filters.vehicle
  const activeFilters = level === 'rider' ? RIDER_FILTERS : FILTERS

  let params
  if (level === 'pivot') params = { ...filters, measure }
  else if (level === 'cube') params = { ...filters, courier: drill.courier }
  else {
    params = {
      year: filters.year, quarter: filters.quarter, month: filters.month, age_band: filters.age_band,
      courier, vehicle, sort, top_n: topN,
    }
  }
  const { rows, loading, error } = useReport('r2', level, params)

  // ---- drill path ----
  const stops = [{ label: 'All couriers' }]
  if (drill.courier) stops.push({ label: drill.courier })
  if (drill.vehicle) stops.push({ label: `${drill.vehicle} riders` })
  const zoomOut = (i) => {
    if (i === 0) setDrill({ courier: null, vehicle: null })
    else setDrill((d) => ({ ...d, vehicle: null }))
  }

  // ---- per-level content ----
  let figures = []
  let columns = []
  let tableRows = rows
  let table = {}
  let note = null
  let legend = []
  let actions = null
  let empty = false
  let exportName = 'r2.csv'

  if (level === 'pivot') {
    const total = rows.find((r) => r.is_total)
    const couriers = rows.filter((r) => !r.is_total)
    empty = !loading && !error && couriers.length === 0
    const maxCell = Math.max(0, ...couriers.flatMap((r) => VEHICLES.map(([k]) => Number(r[k]) || 0)))
    const perRider = measure === 'per_rider'

    const heat = (row, key, vehicleName) => {
      const value = row[key]
      const measureLabel = perRider ? 'orders per rider' : 'orders'
      if (value === null || value === undefined) {
        return (
          <Tooltip text={`No ${row.courier} riders on ${vehicleName.toLowerCase()}`}>
            <span className="cell-muted">–</span>
          </Tooltip>
        )
      }
      const strength = row.is_total || !maxCell ? 0 : (Number(value) || 0) / maxCell
      return (
        <Tooltip
          text={`${row.is_total ? 'All couriers' : row.courier} · ${vehicleName}: ${num(value)} ${measureLabel}${
            row.is_total ? '' : ' — click to see these riders'
          }`}
        >
          <button
            type="button"
            className="heat-cell"
            style={{ '--heat': `${Math.round(6 + strength * 50)}%` }}
            onClick={() => setDrill({ courier: row.is_total ? null : row.courier, vehicle: vehicleName })}
          >
            {num(value)}
          </button>
        </Tooltip>
      )
    }

    figures = [
      perRider
        ? { label: 'Orders per rider', value: num(total?.total) }
        : { label: 'Orders delivered', value: compact(total?.total), title: num(total?.total) },
      { label: 'Active riders', value: num(total?.riders) },
      { label: 'Couriers', value: num(couriers.length) },
    ]
    columns = [
      {
        key: 'courier',
        label: 'Courier',
        render: (r) =>
          r.is_total ? (
            <span className="cell-strong">All couriers</span>
          ) : (
            <button type="button" className="link-cell" onClick={() => setDrill({ courier: r.courier, vehicle: null })}>
              {r.courier}
            </button>
          ),
      },
      ...VEHICLES.map(([key, name]) => ({ key, label: name, align: 'right', tip: true, render: (r) => heat(r, key, name) })),
      {
        key: 'total',
        label: perRider ? 'All vehicles' : 'Total',
        align: 'right',
        render: (r) => <span className="cell-strong">{num(r.total)}</span>,
      },
      { key: 'riders', label: 'Riders', align: 'right', render: (r) => num(r.riders) },
    ]
    table = { caption: 'Orders by courier and vehicle', rowKey: (r) => r.courier, isTotal: (r) => r.is_total }
    actions = <Segmented label="Cells show" options={MEASURES} value={measure} onChange={setMeasure} />
    note = perRider
      ? 'Each cell is orders divided by the riders on that vehicle. Similar numbers across a row mean the work is spread evenly. Click a courier or a cell to see who carries it.'
      : 'Darker cells carry more orders. Click a courier to break it down by vehicle, or a cell to see those riders.'
    legend = [
      { swatch: 'heat', label: `Cell colour = ${perRider ? 'orders per rider' : 'orders'}; darker means more` },
      { swatch: 'total', label: 'Bold row = all couriers' },
      { swatch: 'glyph', glyph: '–', label: 'No riders on that vehicle' },
    ]
    exportName = perRider ? 'r2-courier-vehicle-orders-per-rider.csv' : 'r2-courier-vehicle-orders.csv'
  }

  if (level === 'cube') {
    const cells = rows.filter((r) => r.grouping_level === 0).sort((a, b) => Number(b.orders) - Number(a.orders))
    const subtotal = rows.find((r) => r.grouping_level === 1)
    empty = !loading && !error && cells.length === 0
    const maxOrders = Math.max(0, ...cells.map((r) => Number(r.orders) || 0))
    figures = [
      { label: `${drill.courier} orders`, value: compact(subtotal?.orders), title: num(subtotal?.orders) },
      { label: `${drill.courier} riders`, value: num(subtotal?.riders) },
      { label: 'Orders per rider', value: num(subtotal?.orders_per_rider) },
    ]
    const vehicleLabel = (r) => (r.grouping_level === 1 ? `All ${drill.courier} vehicles` : r.vehicle)
    columns = [
      { key: 'vehicle', label: 'Vehicle', render: (r) => <span className="cell-strong">{vehicleLabel(r)}</span>, csv: vehicleLabel },
      {
        key: 'orders',
        label: 'Orders',
        tip: true,
        render: (r) => (
          <Tooltip
            text={
              r.grouping_level === 1
                ? null
                : `${num(r.orders)} orders — ${pct(r.order_share_pct)} of ${drill.courier}'s orders`
            }
          >
            <Bar value={Number(r.orders)} max={maxOrders} track={r.grouping_level !== 1}>{num(r.orders)}</Bar>
          </Tooltip>
        ),
      },
      { key: 'units', label: 'Units', align: 'right', render: (r) => num(r.units) },
      { key: 'riders', label: 'Riders', align: 'right', render: (r) => num(r.riders) },
      { key: 'orders_per_rider', label: 'Orders per rider', align: 'right', render: (r) => num(r.orders_per_rider) },
      { key: 'order_share_pct', label: `Share of ${drill.courier} orders`, align: 'right', render: (r) => pct(r.order_share_pct) },
    ]
    tableRows = subtotal ? [...cells, subtotal] : cells
    table = {
      caption: `${drill.courier} orders by vehicle`,
      rowKey: (r) => `${r.vehicle}-${r.grouping_level}`,
      isTotal: (r) => r.grouping_level === 1,
      onRowClick: (r) => setDrill((d) => ({ ...d, vehicle: r.vehicle })),
      drillHint: 'Show these riders',
    }
    note = 'Click a vehicle to see its riders. Orders per rider shows whether a vehicle type is carrying more than its share of the load.'
    legend = [
      { swatch: 'bar', label: 'Bar length = orders, relative to the largest vehicle' },
      { swatch: 'total', label: `Bold row = all ${drill.courier} vehicles` },
    ]
    exportName = `r2-${slug(drill.courier)}-vehicles.csv`
  }

  if (level === 'rider') {
    empty = !loading && !error && rows.length === 0
    const orders = rows.map((r) => Number(r.orders) || 0)
    const maxOrders = Math.max(0, ...orders)
    const gap =
      rows.length > 1 && Math.min(...orders) > 0
        ? (100 * (Math.max(...orders) - Math.min(...orders))) / Math.min(...orders)
        : null
    figures = [
      { label: 'Riders listed', value: num(rows.length) },
      { label: 'Average orders per rider', value: rows.length ? num(orders.reduce((a, b) => a + b, 0) / rows.length) : '–' },
      { label: 'Busiest vs quietest listed', value: gap === null ? '–' : `+${dec1(gap)}%`, sub: 'more orders for the busiest rider' },
    ]
    columns = [
      { key: 'workload_rank', label: 'Rank', align: 'right' },
      { key: 'rider', label: 'Rider', render: (r) => <span className="cell-strong">{r.rider}</span> },
      ...(courier ? [] : [{ key: 'courier', label: 'Courier' }]),
      ...(vehicle ? [] : [{ key: 'vehicle', label: 'Vehicle' }]),
      { key: 'age_band', label: 'Age' },
      {
        key: 'orders',
        label: 'Orders',
        tip: true,
        render: (r) => (
          <Tooltip text={`${num(r.orders)} orders — busier than ${pct(r.workload_percentile)} of riders`}>
            <Bar value={Number(r.orders)} max={maxOrders}>{num(r.orders)}</Bar>
          </Tooltip>
        ),
      },
      { key: 'units', label: 'Units', align: 'right', render: (r) => num(r.units) },
      {
        key: 'active_days',
        label: 'Days active',
        align: 'right',
        render: (r) => `${num(r.active_days)} of ${num(r.calendar_days)}`,
        csv: (r) => `${r.active_days} of ${r.calendar_days}`,
      },
      { key: 'avg_orders_per_active_day', label: 'Orders per active day', align: 'right', render: (r) => dec1(r.avg_orders_per_active_day) },
      { key: 'peak_day_orders', label: 'Busiest day', align: 'right', render: (r) => num(r.peak_day_orders) },
      { key: 'workload_percentile', label: 'Busier than', align: 'right', render: (r) => `${pct(r.workload_percentile)} of riders` },
    ]
    table = { caption: 'Rider workload', rowKey: (r, i) => `${r.rider}-${i}` }
    actions = (
      <>
        <Segmented label="Order" options={SORTS} value={sort} onChange={setSort} />
        <Segmented label="Show" options={TOP_N} value={topN} onChange={setTopN} />
      </>
    )
    note = `"Busier than" compares each rider's order count with every rider in this selection. ${
      filters.size_group ? 'The order-size filter does not apply at the rider level. ' : ''
    }Busiest day is the most orders that rider delivered in a single day.`
    legend = [{ swatch: 'bar', label: 'Bar length = orders, relative to the busiest rider listed' }]
    exportName = `r2-riders-${slug([courier, vehicle].filter(Boolean).join(' ') || 'all')}.csv`
  }

  return (
    <div className="report">
      <FilterBar
        defs={activeFilters}
        values={filters}
        locked={{ courier: drill.courier, vehicle: drill.vehicle }}
        onChange={(key, value) => setFilters((f) => changeFilter(f, key, value))}
        onClear={() => setFilters(emptyFilters(FILTERS))}
      />

      {!error && !empty && <Figures items={figures} />}

      <Panel
        loading={loading}
        title={<RoutePath stops={stops} onSelect={zoomOut} />}
        actions={
          <>
            {actions}
            <ExportButton onClick={() => downloadCsv(exportName, columns, tableRows)} disabled={loading || !!error || empty} />
          </>
        }
        subheader={<ScopeLine values={{ ...filters, courier, vehicle }} keys={activeFilters.map((f) => f.key)} />}
        legend={!error && !empty ? <Legend items={legend} /> : null}
        footer={!error && !empty && note}
      >
        <ReportStatus loading={loading} error={error} empty={empty} />
        {!error && !empty && <DataTable columns={columns} rows={tableRows} {...table} />}
      </Panel>
    </div>
  )
}
