// A thin bar behind a number, scaled to the largest value in the table.
// Pass track={false} on total rows so their number lines up without a bar.
export default function Bar({ value, max, children, track = true }) {
  const width = max > 0 && value > 0 ? Math.max(1.5, (100 * Number(value)) / max) : 0
  return (
    <span className="bar-cell">
      <span className="bar-value">{children}</span>
      <span className={`bar-track${track ? '' : ' is-hidden'}`} aria-hidden="true">
        <span className="bar-fill" style={{ width: `${width}%` }} />
      </span>
    </span>
  )
}
