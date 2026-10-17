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
import { YEAR, QUARTER, MONTH, VEHICLE, SIZE_GROUP, emptyFilters, changeFilter } from '../lib/dimensions.js'
import { num, peso, pesoFull, pct, compact } from '../lib/format.js'
import { downloadCsv, slug } from '../lib/csv.js'

// R1 Product & Category Value
//   Category level  -> olap/queries/r1_product_category_value/category.sql
//   Product level   -> olap/queries/r1_product_category_value/product.sql
// Clicking a category drills down to its products; the drill path in the
// panel header rolls back up. Period, vehicle and order size filter both levels.

const FILTERS = [YEAR, QUARTER, MONTH, VEHICLE, SIZE_GROUP]
const FILTER_KEYS = FILTERS.map((f) => f.key)
const TOP_N = [
  { value: '5', label: 'Top 5' },
  { value: '10', label: 'Top 10' },
  { value: '20', label: 'Top 20' },
]

export default function ProductCategoryReport() {
  const [filters, setFilters] = useState(() => emptyFilters(FILTERS))
  const [category, setCategory] = useState(null)
  const [topN, setTopN] = useState('10')

  const level = category ? 'product' : 'category'
  const params = category ? { ...filters, category, top_n: topN } : filters
  const { rows, loading, error } = useReport('r1', level, params)

  const isTotalRow = (r) => (level === 'category' ? r.is_total : r.is_subtotal)
  const total = rows.find(isTotalRow)
  const detail = rows.filter((r) => !isTotalRow(r))
  const empty = !loading && !error && detail.length === 0
  const maxValue = Math.max(0, ...detail.map((r) => Number(r.value) || 0))
  const leader = detail[0]
  const totalUnits = Number(total?.units) || 0
  const unitsScope = level === 'category' ? 'all units' : `${category} units`
  const unitShare = (r) => (totalUnits ? (100 * Number(r.units)) / totalUnits : null)

  const stops = [{ label: 'All categories' }]
  if (category) stops.push({ label: category })

  const figures =
    level === 'category'
      ? [
          { label: 'Units delivered', value: compact(total?.units), title: num(total?.units) },
          { label: 'List-price value', value: peso(total?.value), title: pesoFull(total?.value) },
          {
            label: 'Leading category',
            value: leader?.category ?? '–',
            text: true,
            sub: leader ? `${pct(leader.value_share_pct)} of list-price value` : null,
          },
        ]
      : [
          { label: `${category} units delivered`, value: compact(total?.units), title: num(total?.units) },
          { label: `${category} list-price value`, value: peso(total?.value), title: pesoFull(total?.value) },
          {
            label: 'Top product',
            value: leader?.product ?? '–',
            text: true,
            sub: leader ? `${peso(leader.value)} list-price value` : null,
          },
        ]

  const columns =
    level === 'category'
      ? [
          { key: 'value_rank', label: 'Rank', align: 'right', render: (r) => (r.is_total ? '' : r.value_rank) },
          { key: 'category', label: 'Category', render: (r) => <span className="cell-strong">{r.category}</span> },
          {
            key: 'units',
            label: 'Units delivered',
            align: 'right',
            tip: true,
            render: (r) => (
              <Tooltip
                text={
                  r.is_total || r.is_subtotal
                    ? null
                    : `${num(r.units)} units — ${pct(unitShare(r))} of ${unitsScope}`
                }
              >
                {num(r.units)}
              </Tooltip>
            ),
          },
          {
            key: 'value',
            label: 'List-price value',
            tip: true,
            render: (r) => (
              <Tooltip
                text={
                  r.is_total ? null : `${pesoFull(r.value)} — ${pct(r.value_share_pct)} of list-price value`
                }
              >
                <Bar value={Number(r.value)} max={maxValue} track={!r.is_total}>{peso(r.value)}</Bar>
              </Tooltip>
            ),
          },
          { key: 'value_share_pct', label: 'Share of value', align: 'right', render: (r) => pct(r.value_share_pct) },
        ]
      : [
          { key: 'rank_in_category', label: 'Rank', align: 'right', render: (r) => (r.is_subtotal ? '' : r.rank_in_category) },
          {
            key: 'product',
            label: 'Product',
            render: (r) => <span className="cell-strong">{r.is_subtotal ? `All ${r.category} products` : r.product}</span>,
            csv: (r) => (r.is_subtotal ? `All ${r.category} products` : r.product),
          },
          {
            key: 'units',
            label: 'Units delivered',
            align: 'right',
            tip: true,
            render: (r) => (
              <Tooltip
                text={
                  r.is_total || r.is_subtotal
                    ? null
                    : `${num(r.units)} units — ${pct(unitShare(r))} of ${unitsScope}`
                }
              >
                {num(r.units)}
              </Tooltip>
            ),
          },
          {
            key: 'value',
            label: 'List-price value',
            tip: true,
            render: (r) => (
              <Tooltip
                text={
                  r.is_subtotal ? null : `${pesoFull(r.value)} — ${pct(r.share_of_category_pct)} of ${r.category}`
                }
              >
                <Bar value={Number(r.value)} max={maxValue} track={!r.is_subtotal}>{peso(r.value)}</Bar>
              </Tooltip>
            ),
          },
          { key: 'share_of_category_pct', label: 'Share of category', align: 'right', render: (r) => pct(r.share_of_category_pct) },
        ]

  const exportRows = () =>
    downloadCsv(category ? `r1-products-${slug(category)}.csv` : 'r1-categories.csv', columns, rows)

  const legend = [
    { swatch: 'bar', label: 'Bar length = list-price value, relative to the largest row shown' },
    {
      swatch: 'total',
      label: level === 'category' ? 'Bold row = all categories' : `Bold row = all ${category} products`,
    },
    { swatch: 'glyph', glyph: '–', label: 'No data' },
  ]

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
        title={<RoutePath stops={stops} onSelect={() => setCategory(null)} />}
        actions={
          <>
            {category && <Segmented label="Show" options={TOP_N} value={topN} onChange={setTopN} />}
            <ExportButton onClick={exportRows} disabled={loading || !!error || empty} />
          </>
        }
        subheader={<ScopeLine values={filters} keys={FILTER_KEYS} />}
        legend={!error && !empty ? <Legend items={legend} /> : null}
        footer={
          !error && !empty && (
            <>
              {level === 'category'
                ? 'Click a category to see its leading products. '
                : `The last row covers every ${category} product, not only the ones listed. `}
              List-price value is units times each product's current list price. The source keeps no price history,
              so read it as basket value, not revenue.
            </>
          )
        }
      >
        <ReportStatus loading={loading} error={error} empty={empty} />
        {!error && !empty && (
          <DataTable
            caption={level === 'category' ? 'Units and value by category' : `Top products in ${category}`}
            columns={columns}
            rows={rows}
            rowKey={(r, i) => `${r.category}-${r.product ?? ''}-${i}`}
            isTotal={isTotalRow}
            onRowClick={level === 'category' ? (r) => setCategory(r.category) : undefined}
            drillHint="Show this category's products"
          />
        )}
      </Panel>
    </div>
  )
}
