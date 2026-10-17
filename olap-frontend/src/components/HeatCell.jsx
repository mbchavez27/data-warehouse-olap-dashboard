import Tooltip from './Tooltip.jsx'
import { num } from '../lib/format.js'

// One cell of a heat matrix: its fill strength is its share of the largest cell
// in the table, with the exact reading in a tooltip. A null value renders the
// no-data glyph instead, and `emptyTip` explains why.
//   value    the cell's number (or null)
//   max      the largest cell in the table, used to scale the fill
//   tip      tooltip text for a filled cell
//   emptyTip tooltip text for a null cell (optional)
//   onClick  drill action; without it the cell is a plain, non-interactive block
export default function HeatCell({ value, max, tip, emptyTip, onClick }) {
  if (value === null || value === undefined) {
    const missing = <span className="cell-muted">–</span>
    return emptyTip ? <Tooltip text={emptyTip}>{missing}</Tooltip> : missing
  }

  const strength = max ? (Number(value) || 0) / max : 0
  const style = { '--heat': `${Math.round(6 + strength * 50)}%` }
  const label = num(value)

  return (
    <Tooltip text={tip}>
      {onClick ? (
        <button type="button" className="heat-cell" style={style} onClick={onClick}>
          {label}
        </button>
      ) : (
        <span className="heat-cell is-static" style={style}>
          {label}
        </span>
      )}
    </Tooltip>
  )
}
