import { useState } from 'react'
import { createPortal } from 'react-dom'

// Hover/focus hint that explains what a mark shows (full value, its share, how
// to read it). The bubble renders in a portal with position: fixed, because the
// panel and the table both clip their overflow. `text` of null/'' renders the
// children bare, for rows that should not have a hint. `className`/`style` land
// on the wrapper, so a caller (a calendar cell, say) can style and place it.
export default function Tooltip({ text, className, style, children }) {
  const [anchor, setAnchor] = useState(null)

  if (!text) return children

  const open = (el) => {
    const r = el.getBoundingClientRect()
    setAnchor({ x: r.left + r.width / 2, y: r.top, below: r.top < 64 })
  }

  return (
    <span
      className={className ? `tip ${className}` : 'tip'}
      style={style}
      onMouseEnter={(e) => open(e.currentTarget)}
      onMouseLeave={() => setAnchor(null)}
      onFocus={(e) => open(e.currentTarget)}
      onBlur={() => setAnchor(null)}
    >
      {children}
      {anchor &&
        createPortal(
          <span
            className={`tip-bubble${anchor.below ? ' is-below' : ''}`}
            role="tooltip"
            style={{ left: anchor.x, top: anchor.y }}
          >
            {text}
          </span>,
          document.body,
        )}
    </span>
  )
}
