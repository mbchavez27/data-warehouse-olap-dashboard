// Report table. Columns: { key, label, align?, render?(row), title?(row), tip? }.
// Rows with isTotal() get the total style; rows that canDrill() are clickable
// and keyboard-focusable. A column with tip: true renders its own Tooltip, so
// the row's drill hint moves to the other cells instead of the whole row.
export default function DataTable({ columns, rows, rowKey, onRowClick, canDrill, isTotal, caption, drillHint }) {
  return (
    <div className="table-wrap">
      <table>
        {caption && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.align === 'right' ? 'num' : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
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
