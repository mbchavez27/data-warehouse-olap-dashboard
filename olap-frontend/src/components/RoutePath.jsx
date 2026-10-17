// The drill path as a breadcrumb: All categories › Appliances. Each item is a
// level you drilled into; clicking an earlier one rolls the report back up.
export default function RoutePath({ stops, onSelect }) {
  return (
    <nav className="route" aria-label="Report level">
      <ol className="route-stops">
        {stops.map((stop, i) => {
          const current = i === stops.length - 1
          return (
            <li key={`${i}-${stop.label}`} className={`route-stop${current ? ' is-current' : ''}`}>
              {i > 0 && (
                <svg className="route-sep" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="m6 3.5 4.5 4.5L6 12.5" />
                </svg>
              )}
              {current ? (
                <span className="route-label" aria-current="location">
                  {stop.label}
                </span>
              ) : (
                <button type="button" className="route-label" onClick={() => onSelect(i)}>
                  {stop.label}
                </button>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
