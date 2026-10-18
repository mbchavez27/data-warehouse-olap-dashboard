import { useState } from 'react'
import { chartKeys, KEYS_HINT } from '../lib/chartKeys.js'

// A small SVG line chart. Points are evenly spaced left to right; the first
// series also fills below its line. No chart library: the path is built from
// the values and the axes are plain SVG. Hovering shows the exact reading.
//
//   labels   string[]                       one x label per point
//   series   { name, values, dashed? }[]    one line each; `values` are numbers
//   format   (v) => string                  hover formatting
//   axisFormat (v) => string                y-axis labels (defaults to format)
//   title    string                         accessible name for the chart

// Round gridlines: a step of 1, 2 or 5 x 10^n that gives about `count` lines,
// with the top of the scale on the first step at or above the peak.
function niceTicks(peak, count = 4) {
  if (!(peak > 0)) return [0, 1]
  const raw = peak / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw)
  const top = Math.ceil(peak / step) * step
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)
}

export default function LineChart({ labels, series, format = String, axisFormat = format, title = 'Chart' }) {
  const [hover, setHover] = useState(null)

  if (!labels.length) return null

  const W = 720
  const H = 260
  const pad = { l: 56, r: 16, t: 16, b: 34 }
  const n = labels.length
  const numbers = series.flatMap((s) => s.values.map(Number)).filter(Number.isFinite)
  const peak = numbers.length ? Math.max(...numbers) : 0
  const gridValues = niceTicks(peak)
  const yMax = gridValues[gridValues.length - 1]

  const x = (i) => (n === 1 ? W / 2 : pad.l + (i * (W - pad.l - pad.r)) / (n - 1))
  const y = (v) => H - pad.b - ((Number(v) || 0) / yMax) * (H - pad.t - pad.b)
  const path = (values) => values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = (values) =>
    `${path(values)} L${x(n - 1).toFixed(1)},${H - pad.b} L${x(0).toFixed(1)},${H - pad.b} Z`

  const labelEvery = Math.max(1, Math.ceil(n / 8))

  // Nearest point to the cursor: the overlay rect covers the plot area, so the
  // pointer never has to land exactly on a 2px line.
  const track = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const at = ((e.clientX - r.left) / r.width) * W
    let best = 0
    for (let i = 1; i < n; i++) if (Math.abs(x(i) - at) < Math.abs(x(best) - at)) best = i
    setHover(best)
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
              {axisFormat(gv)}
            </text>
          </g>
        ))}

        {labels.map((label, i) =>
          i % labelEvery === 0 || i === n - 1 ? (
            <text key={`${label}-${i}`} x={x(i)} y={H - pad.b + 20} className="chart-axis" textAnchor="middle">
              {label}
            </text>
          ) : null,
        )}

        {series[0] && <path d={area(series[0].values)} className="chart-area" />}
        {series.map((s) => (
          <path key={s.name} d={path(s.values)} className={`chart-line${s.dashed ? ' is-dashed' : ''}`} />
        ))}

        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={H - pad.b} className="chart-crosshair" />
            {series.map((s) => (
              <circle key={s.name} cx={x(hover)} cy={y(s.values[hover])} r="3.5" className="chart-dot" />
            ))}
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
          : `${labels[hover]}: ${series.map((s) => `${s.name} ${format(s.values[hover])}`).join(', ')}`}
      </p>

      {hover !== null && (
        <div className="chart-tip" style={{ left: `${(100 * x(hover)) / W}%` }}>
          <strong>{labels[hover]}</strong>
          {series.map((s) => (
            <span key={s.name}>
              <i className={s.dashed ? 'is-dashed' : undefined} />
              {s.name}: {format(s.values[hover])}
            </span>
          ))}
        </div>
      )}

      {series.length > 1 && (
        <ul className="chart-legend">
          {series.map((s) => (
            <li key={s.name}>
              <i className={s.dashed ? 'is-dashed' : undefined} />
              {s.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
