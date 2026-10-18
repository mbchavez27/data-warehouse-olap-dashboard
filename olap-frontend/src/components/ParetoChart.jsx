import { useState } from 'react'
import { chartKeys, KEYS_HINT } from '../lib/chartKeys.js'

// Concentration chart: one bar per group plus a cumulative line over them (the
// classic Pareto). Both series share a single 0-100 scale, so the line reaching
// 100 reads as "these groups are everything". Hand-rolled SVG, no library.
//
//   labels      string[]  one per group, left to right
//   values      number[]  the bar series (each group's share, in %)
//   cumulative  number[]  the line series (running total, in %)
//   format      (v) => string
//   barName / lineName    legend and hover names
//   lineHint    what the line means, shown beside its name in the legend (optional)
//   reference / referenceName   a dashed level line and its legend name
//               (optional; e.g. 80 for "80% of value")
//   title       accessible name
//   max         top of the scale; pass it to pin the axis (a Pareto of shares
//               wants 100 so the cumulative line lands on the top gridline)
export default function ParetoChart({
  labels,
  values,
  cumulative,
  format = String,
  barName = 'Share',
  lineName = 'Cumulative',
  lineHint,
  title = 'Concentration',
  max,
  reference,
  referenceName,
}) {
  const [hover, setHover] = useState(null)

  if (!labels.length) return null

  const W = 720
  const H = 260
  const pad = { l: 56, r: 16, t: 16, b: 34 }
  const n = labels.length
  const numbers = [...values, ...cumulative].map(Number).filter(Number.isFinite)
  const pinned = Number.isFinite(Number(max)) ? Number(max) : null
  const peak = numbers.length ? Math.max(...numbers) : 0
  const yMax = pinned ?? (peak > 0 ? peak * 1.08 : 1)
  const step = (W - pad.l - pad.r) / n
  const x = (i) => pad.l + step * (i + 0.5)
  const y = (v) => H - pad.b - ((Number(v) || 0) / yMax) * (H - pad.t - pad.b)

  const barWidth = Math.max(2, step * 0.62)
  const path = cumulative.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const gridValues = [0, 0.5, 1].map((f) => yMax * f)
  const labelEvery = Math.max(1, Math.ceil(n / 12))

  const track = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const at = ((e.clientX - r.left) / r.width) * W
    setHover(Math.max(0, Math.min(n - 1, Math.floor((at - pad.l) / step))))
  }

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart-svg"
        role="img"
        aria-label={`${title}. ${KEYS_HINT}`}
        {...chartKeys(n, hover, setHover)}
      >
        {gridValues.map((gv) => (
          <g key={gv}>
            <line x1={pad.l} x2={W - pad.r} y1={y(gv)} y2={y(gv)} className="chart-grid" />
            <text x={pad.l - 8} y={y(gv) + 4} className="chart-axis" textAnchor="end">
              {format(gv)}
            </text>
          </g>
        ))}

        {values.map((v, i) => (
          <rect
            key={`bar-${labels[i]}`}
            x={x(i) - barWidth / 2}
            y={y(v)}
            width={barWidth}
            height={Math.max(0, H - pad.b - y(v))}
            className={`chart-bar${hover === i ? ' is-on' : ''}`}
          />
        ))}

        {Number.isFinite(reference) && (
          <line x1={pad.l} x2={W - pad.r} y1={y(reference)} y2={y(reference)} className="chart-reference" />
        )}

        <path d={path} className="chart-line" />

        {labels.map((label, i) =>
          i % labelEvery === 0 || i === n - 1 ? (
            <text key={`${label}-${i}`} x={x(i)} y={H - pad.b + 20} className="chart-axis" textAnchor="middle">
              {label}
            </text>
          ) : null,
        )}

        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={H - pad.b} className="chart-crosshair" />
            <circle cx={x(hover)} cy={y(cumulative[hover])} r="3.5" className="chart-dot" />
          </g>
        )}

        <rect
          x={pad.l}
          y={pad.t}
          width={W - pad.l - pad.r}
          height={H - pad.t - pad.b}
          fill="transparent"
          onMouseMove={track}
          onMouseLeave={() => setHover(null)}
        />
      </svg>

      <p className="visually-hidden" aria-live="polite">
        {hover === null
          ? ''
          : `${labels[hover]}: ${barName} ${format(values[hover])}, ${lineName} ${format(cumulative[hover])}`}
      </p>

      {hover !== null && (
        <div className="chart-tip" style={{ left: `${(100 * x(hover)) / W}%` }}>
          <strong>{labels[hover]}</strong>
          <span>
            <i className="is-bar" />
            {barName}: {format(values[hover])}
          </span>
          <span>
            <i />
            {lineName}: {format(cumulative[hover])}
          </span>
        </div>
      )}

      <ul className="chart-legend">
        <li>
          <i className="is-bar" />
          {barName}
        </li>
        <li>
          <i />
          {lineName}
          {lineHint && <span className="chart-legend-hint">— {lineHint}</span>}
        </li>
        {Number.isFinite(reference) && referenceName && (
          <li>
            <i className="is-dashed" />
            {referenceName}
          </li>
        )}
      </ul>
    </div>
  )
}
