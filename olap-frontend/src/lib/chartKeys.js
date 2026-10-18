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

export const KEYS_HINT = 'Focus the chart and use the arrow keys to read each point.'
