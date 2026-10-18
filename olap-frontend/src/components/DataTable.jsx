import { useState } from 'react'
import Tooltip from './Tooltip.jsx'

// Report table. Columns: { key, label, align?, render?(row), title?(row), tip?, hint?, sortValue?(row) }.
// A column with a hint gets a dotted-underlined header that explains the column
// on hover or keyboard focus.
// Rows with isTotal() get the total style; rows that canDrill() are clickable
// and keyboard-focusable. A column with tip: true renders its own Tooltip, so
// the row's drill hint moves to the other cells instead of the whole row.
//
// sortable: headers become buttons that sort the rows. Numbers sort busiest
// first on the first click, text A-Z; a second click flips it and a third
// restores the query's own order. Total rows stay pinned where they were (top
// or bottom). Leave it off for tables whose row order is a hierarchy (months
// under quarters, gender rows under a location). The sort resets when the
// caption changes, i.e. on a drill to another level.
const missing = (v) => v === null || v === undefined || v === ''
const valueOf = (column, row) => (column.sortValue ? column.sortValue(row) : row[column.key])

// A column sorts as numbers when its non-total cells are numbers (the API may
// send NUMERIC as strings), otherwise as text.
export const isNumericColumn = (column, rows, isTotal) =>
  rows.some((r) => !isTotal?.(r) && !missing(valueOf(column, r)) && Number.isFinite(Number(valueOf(column, r))))

// The rows in `sort` order ({ key, dir: 'asc' | 'desc' }), blanks last either
// way. Totals at the top stay at the top; every other total goes to the bottom.
export function sortRows(rows, column, dir, isTotal) {
  const numeric = isNumericColumn(column, rows, isTotal)
  const sign = dir === 'asc' ? 1 : -1
  const compare = (a, b) => {
    const va = valueOf(column, a)
    const vb = valueOf(column, b)
    if (missing(va) || missing(vb)) return missing(va) - missing(vb)
    return sign * (numeric ? Number(va) - Number(vb) : String(va).localeCompare(String(vb)))
  }
  let lead = 0
  while (lead < rows.length && isTotal?.(rows[lead])) lead++
  const rest = rows.slice(lead)
  return [...rows.slice(0, lead), ...rest.filter((r) => !isTotal?.(r)).sort(compare), ...rest.filter((r) => isTotal?.(r))]
}

export default function DataTable({ columns, rows, rowKey, onRowClick, canDrill, isTotal, caption, drillHint, sortable = false }) {
  const [sort, setSort] = useState(null) // { caption, key, dir: 'asc' | 'desc' }
  const active = sortable && sort && sort.caption === caption && columns.some((c) => c.key === sort.key) ? sort : null
  const shown = active ? sortRows(rows, columns.find((c) => c.key === active.key), active.dir, isTotal) : rows

  const toggle = (c) => {
    const first = isNumericColumn(c, rows, isTotal) ? 'desc' : 'asc'
    if (!active || active.key !== c.key) setSort({ caption, key: c.key, dir: first })
    else if (active.dir === first) setSort({ caption, key: c.key, dir: first === 'desc' ? 'asc' : 'desc' })
    else setSort(null)
  }

  const header = (c) => {
    const on = active?.key === c.key
    if (sortable) {
      const button = (
        <button
          type="button"
          className={['th-sort', c.hint && 'th-hint', on && 'is-on'].filter(Boolean).join(' ')}
          onClick={() => toggle(c)}
        >
          {c.label}
          <span className="th-arrow" aria-hidden="true">
            {on ? (active.dir === 'asc' ? '▲' : '▼') : '↕'}
          </span>
        </button>
      )
      return c.hint ? <Tooltip text={c.hint}>{button}</Tooltip> : button
    }
    if (c.hint) {
      return (
        <Tooltip text={c.hint}>
          <span className="th-hint" tabIndex={0}>
            {c.label}
          </span>
        </Tooltip>
      )
    }
    return c.label
  }

  return (
    <div className="table-wrap">
      <table>
        {caption && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={c.align === 'right' ? 'num' : undefined}
                aria-sort={active?.key === c.key ? (active.dir === 'asc' ? 'ascending' : 'descending') : undefined}
              >
                {header(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => {
            const total = isTotal?.(row)
            const clickable = Boolean(onRowClick) && !total && (canDrill ? canDrill(row) : true)
            const classes = [total && 'is-total', clickable && 'is-clickable'].filter(Boolean).join(' ')
            return (
              <tr
                key={rowKey ? rowKey(row, i) : i}
                className={classes || undefined}
                onClick={clickable ? () => onRowClick(row) : undefined}
                onKeyDown={
                  clickable
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          onRowClick(row)
                        }
                      }
                    : undefined
                }
                tabIndex={clickable ? 0 : undefined}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={c.align === 'right' ? 'num' : undefined}
                    title={c.tip ? undefined : c.title ? c.title(row) : clickable ? drillHint : undefined}
                  >
                    {c.render ? c.render(row) : row[c.key]}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
