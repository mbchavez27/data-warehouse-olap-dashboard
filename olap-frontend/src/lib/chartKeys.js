// Keyboard reading for a chart, so its hover readout isn't mouse-only.
// Spread the result onto the chart's <svg>: Tab focuses the chart and shows the
// first point, Left/Right step through the points, Home/End jump to the ends,
// Escape hides the readout and blur clears it.
//   count       how many points the chart has
//   current     the index on show, or null
//   setCurrent  the chart's hover setter
export function chartKeys(count, current, setCurrent) {
  const moves = {
    ArrowRight: (c) => c + 1,
    ArrowLeft: (c) => c - 1,
    Home: () => 0,
    End: () => count - 1,
  }
  return {
    tabIndex: 0,
    onFocus: () => setCurrent((c) => c ?? 0),
    onBlur: () => setCurrent(null),
    onKeyDown: (e) => {
      if (e.key === 'Escape') {
        setCurrent(null)
        return
      }
      const move = moves[e.key]
      if (!move || !count) return
      e.preventDefault()
      setCurrent(Math.max(0, Math.min(count - 1, move(current ?? 0))))
    },
  }
}

// Pointer position in the chart's own viewBox units: measured against the whole
// <svg>, since an overlay covering only the plot area would skew the mapping.
export function svgPoint(e, W, H) {
  const svg = e.currentTarget.ownerSVGElement ?? e.currentTarget
  const r = svg.getBoundingClientRect()
  return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H }
}

// Pointer handlers for a chart's hover readout, so mouse, pen and touch all
// work: a tap or press shows the nearest point, a drag scrubs. A finger lifting
// fires pointerleave at once, so touch keeps its reading until the chart loses
// focus (a tap elsewhere) instead of flashing it away.
export const pointerReadout = (track, clear) => ({
  onPointerDown: track,
  onPointerMove: track,
  onPointerLeave: (e) => {
    if (e.pointerType !== 'touch') clear()
  },
})

// Where a readout bubble sits: over its point, but kept 15% in from either
// edge so a bubble for the first or last point isn't cut off, on a phone most.
export const tipLeft = (x, W) => `${Math.min(85, Math.max(15, (100 * x) / W))}%`

export const KEYS_HINT = 'Focus the chart and use the arrow keys to read each point.'
