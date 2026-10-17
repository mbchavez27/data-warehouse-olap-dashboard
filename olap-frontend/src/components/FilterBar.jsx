import { FilterIcon } from './Icons.jsx'

// Compact filter toolbar. Each control reads "Year  All ▾". Filters that
// aren't "All" turn blue; values pinned by the drill path (e.g. the courier
// you clicked into) turn amber and lock until you zoom back out.
export default function FilterBar({ defs, values, onChange, onClear, locked = {} }) {
  const hasActive = defs.some((d) => values[d.key] && locked[d.key] == null)
  return (
    <div className="filters" role="group" aria-label="Filters">
      <span className="filters-title">
        <FilterIcon className="filters-icon" />
        Filters
      </span>
      {defs.map((def) => {
        const options = def.getOptions ? def.getOptions(values) : def.options
        const pinned = locked[def.key]
        const isPinned = pinned !== undefined && pinned !== null && pinned !== ''
        const value = isPinned ? pinned : values[def.key] ?? ''
        const state = isPinned ? ' is-pinned' : value ? ' is-active' : ''
        return (
          <label key={def.key} className={`filter${state}`}>
            <span className="filter-label">{def.label}</span>
            <select
              value={value}
              disabled={isPinned}
              title={isPinned ? 'Set by the drill path. Zoom out to change it.' : undefined}
              onChange={(e) => onChange(def.key, e.target.value)}
            >
              {isPinned && !options.some((o) => o.value === pinned) && <option value={pinned}>{pinned}</option>}
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        )
      })}
      {onClear && (
        <button type="button" className="text-button" onClick={onClear} disabled={!hasActive}>
          Clear all
        </button>
      )}
    </div>
  )
}
