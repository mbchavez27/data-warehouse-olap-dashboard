// Number formatting for report cells. The Go API may send Postgres NUMERIC
// values as strings, so every formatter converts with Number() first.

const whole = new Intl.NumberFormat('en-PH', { maximumFractionDigits: 0 })
const oneDp = new Intl.NumberFormat('en-PH', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const pesoWhole = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', maximumFractionDigits: 0 })

const missing = (v) => v === null || v === undefined || v === '' || Number.isNaN(Number(v))

export const num = (v) => (missing(v) ? '–' : whole.format(Number(v)))
export const dec1 = (v) => (missing(v) ? '–' : oneDp.format(Number(v)))
export const pct = (v) => (missing(v) ? '–' : `${oneDp.format(Number(v))}%`)
export const pesoFull = (v) => (missing(v) ? '–' : pesoWhole.format(Number(v)))

// ₱54.8B, ₱612.3M, ₱48.1K: short enough for table cells; pesoFull goes in the tooltip.
export function peso(v) {
  if (missing(v)) return '–'
  const x = Number(v)
  const abs = Math.abs(x)
  if (abs >= 1e9) return `₱${oneDp.format(x / 1e9)}B`
  if (abs >= 1e6) return `₱${oneDp.format(x / 1e6)}M`
  if (abs >= 1e3) return `₱${oneDp.format(x / 1e3)}K`
  return `₱${whole.format(x)}`
}

// Compact counts for headline figures: 10,999,917 -> 11.0M
export function compact(v) {
  if (missing(v)) return '–'
  const x = Number(v)
  const abs = Math.abs(x)
  if (abs >= 1e6) return `${oneDp.format(x / 1e6)}M`
  if (abs >= 1e4) return `${whole.format(x / 1e3)}K`
  return whole.format(x)
}
