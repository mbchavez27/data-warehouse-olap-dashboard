import { useState } from 'react'
import { chartKeys, KEYS_HINT, pointerReadout, svgPoint, tipLeft } from '../lib/chartKeys.js'

// Spread of one measure across a set of items: one dot per item on a single
// axis, a median marker, and a shaded "even share" band around the median.
// The axis spans a fixed ±range% of the median (widened only to fit an
// outlier), so a small spread reads small instead of being stretched to fill
// the chart. Dots that would overlap stack upward, packed closer once the
// stack would pass MAX_STACK px. Hand-rolled SVG, no library.
//
//   points  { key, value, label }[]   one dot each; `label` heads the hover tip
//   format  (v) => string             axis and hover formatting
//   band    % either side of the median that is shaded (default 5)
//   range   % either side of the median the axis covers (default 10)
//   noun    what one dot is, for the key ("rider")
//   title   accessible name
const MAX_STACK = 96

export default function DotStrip({ points, format = String, band = 5, range = 10, noun = 'item', title = 'Spread' }) {
  const [hover, setHover] = useState(null)

  const values = points.map((p) => Number(p.value)).filter(Number.isFinite)
  if (!values.length) return null

  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
  const lo = Math.min(median * (1 - range / 100), sorted[0])
  const hi = Math.max(median * (1 + range / 100), sorted[sorted.length - 1])

  const W = 720
  const r = 4.5
  const pad = { l: 16, r: 16, t: 22, b: 48 }
  const x = (v) => (hi === lo ? W / 2 : pad.l + ((v - lo) / (hi - lo)) * (W - pad.l - pad.r))

  // Stack each dot on the lowest row with no dot closer than a diameter.
  const rows = []
  const placed = points
    .filter((p) => Number.isFinite(Number(p.value)))
    .map((p) => ({ ...p, cx: x(Number(p.value)) }))
    .sort((a, b) => a.cx - b.cx)
    .map((p) => {
      let row = rows.findIndex((last) => p.cx - last >= 2 * r + 1)
      if (row === -1) row = rows.push(-Infinity) - 1
      rows[row] = p.cx
      return { ...p, row }
    })
  const step = Math.min(2 * r + 1, MAX_STACK / rows.length)
  const H = Math.max(110, pad.t + 12 + rows.length * step + pad.b)
  const base = H - pad.b - r - 4
  const cy = (row) => base - row * step

  const bandLo = x(median * (1 - band / 100))
  const bandHi = x(median * (1 + band / 100))
  const ticks = [lo, median * (1 - band / 100), median, median * (1 + band / 100), hi]
  // Under each tick, its distance from the median ("−5%"), or "median".
  const offset = (t) => {
    const d = Math.round(((t - median) / median) * 100)
    return d === 0 ? 'median' : `${d > 0 ? '+' : '−'}${Math.abs(d)}%`
  }
  const on = hover === null ? null : placed[hover] // hover is an index into placed, left to right
  // The dot nearest the pointer, so a finger needn't land on a 9px circle.
  const track = (e) => {
    const at = svgPoint(e, W, H)
    let best = 0
    placed.forEach((p, i) => {
      const d = (p.cx - at.x) ** 2 + (cy(p.row) - at.y) ** 2
      const bestD = (placed[best].cx - at.x) ** 2 + (cy(placed[best].row) - at.y) ** 2
      if (d < bestD) best = i
    })
    setHover(best)
  }
  const vsMedian = (v) => `${v >= median ? '+' : ''}${(((Number(v) - median) / median) * 100).toFixed(1)}% against the median`

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart-svg"
        role="img"
        aria-label={`${title}. ${KEYS_HINT}`}
        {...chartKeys(placed.length, hover, setHover)}
        {...pointerReadout(track, () => setHover(null))}
      >
        <rect x={bandLo} y={pad.t} width={bandHi - bandLo} height={H - pad.b - pad.t} className="strip-band" />
        <line x1={pad.l} x2={W - pad.r} y1={H - pad.b} y2={H - pad.b} className="chart-grid" />
        <line x1={x(median)} x2={x(median)} y1={pad.t} y2={H - pad.b} className="strip-median" />

        {/* Direct labels, so the strip reads without its key. */}
        <text x={bandLo + 4} y={pad.t - 7} className="strip-label">
          Even share (±{band}%)
        </text>
        <text x={x(median) + 4} y={pad.t - 7} className="strip-label is-median">
          Median
        </text>

        {ticks.map((t, i) => (
          <g key={i}>
            <text x={x(t)} y={H - pad.b + 18} className="chart-axis" textAnchor="middle">
              {format(t)}
            </text>
            <text x={x(t)} y={H - pad.b + 32} className="chart-axis is-sub" textAnchor="middle">
              {offset(t)}
            </text>
          </g>
        ))}

        {placed.map((p, i) => (
          <circle
            key={p.key}
            cx={p.cx}
            cy={cy(p.row)}
            r={r}
            className={`strip-dot${hover === i ? ' is-on' : ''}`}
          />
        ))}
      </svg>

      <p className="visually-hidden" aria-live="polite">
        {on ? `${on.label}: ${format(on.value)}, ${vsMedian(on.value)}` : ''}
      </p>

      {on && (
        <div className="chart-tip" style={{ left: tipLeft(on.cx, W) }}>
          <strong>{on.label}</strong>
          <span>{`${format(on.value)} — ${vsMedian(on.value)}`}</span>
        </div>
      )}

      <ul className="chart-legend">
        <li>
          <i className="is-dot" />
          One {noun}
        </li>
        <li>
          <i className="is-median" />
          Median, {format(median)}
        </li>
        <li>
          <i className="is-band" />
          Within {band}% of the median
        </li>
      </ul>
    </div>
  )
}
