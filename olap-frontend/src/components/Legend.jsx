// Key for the visual encodings a report uses: bar length, heat intensity,
// glyphs and total rows. Explanations of the measures themselves live in the
// panel footer; this only says what each mark means.
// Item: { swatch: 'bar' | 'heat' | 'glyph' | 'total', glyph?, label }

function Swatch({ swatch, glyph }) {
  if (swatch === 'bar') return <span className="legend-bar" />
  if (swatch === 'heat') return <span className="legend-heat" />
  if (swatch === 'total') return <span className="legend-total" />
  return <span className="legend-glyph">{glyph}</span>
}

export default function Legend({ items }) {
  return (
    <div className="legend" role="group" aria-label="Legend">
      <span className="legend-title">Legend</span>
      <ul className="legend-items">
        {items.map((item) => (
          <li key={item.label} className="legend-item">
            <span className="legend-swatch" aria-hidden="true">
              <Swatch swatch={item.swatch} glyph={item.glyph} />
            </span>
            <span className="legend-label">{item.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
