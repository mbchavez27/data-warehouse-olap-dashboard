import Tooltip from './Tooltip.jsx'
import { num } from '../lib/format.js'

// One cell of a heat matrix: its fill strength is its share of the largest cell
// in the table, with the exact reading in a tooltip. A null value renders the
// no-data glyph instead, and `emptyTip` explains why.
//   value    the cell's number (or null)
//   max      the largest cell in the table, used to scale the fill
//   strength 0-1 fill strength, in place of value / max (optional); for a
//            diverging scale, where the fill is a deviation, not the value
//   below    fill with the "below" tone instead of the main one (optional)
//   tip      tooltip text for a filled cell
//   emptyTip tooltip text for a null cell (optional)
//   onClick  drill action; without it the cell is a plain, non-interactive block
// Fill strength for a cell on a diverging scale: its distance from the
// average, reaching full colour at FULL_DEVIATION_PCT. A fixed point, not the
// table's largest gap, so a table of ±1% gaps stays pale instead of
// stretching noise to full colour.
export const FULL_DEVIATION_PCT = 10
export const deviationStrength = (deviation) => Math.min(1, Math.abs(deviation ?? 0) / FULL_DEVIATION_PCT)

export default function HeatCell({ value, max, strength, below = false, tip, emptyTip, onClick }) {
  if (value === null || value === undefined) {
    const missing = <span className="cell-muted">–</span>
    return emptyTip ? <Tooltip text={emptyTip}>{missing}</Tooltip> : missing
  }

  const fill = strength ?? (max ? (Number(value) || 0) / max : 0)
  const style = { '--heat': `${Math.round(6 + fill * 50)}%` }
  const label = num(value)
  const classes = ['heat-cell', !onClick && 'is-static', below && 'is-below'].filter(Boolean).join(' ')

  return (
    <Tooltip text={tip}>
      {onClick ? (
        <button type="button" className={classes} style={style} onClick={onClick}>
          {label}
        </button>
      ) : (
        <span className={classes} style={style}>
          {label}
        </span>
      )}
    </Tooltip>
  )
}
