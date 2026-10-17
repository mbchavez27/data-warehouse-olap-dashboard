// One sentence that says exactly which slice of the data is on screen, e.g.
// "Showing JNT motorcycle deliveries, heavy orders only, in Q1 2025."
// `values` = filters plus anything pinned by the drill path; `keys` = the
// filters that apply at the current level.
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December']

export default function ScopeLine({ values, keys }) {
  const on = (k) => keys.includes(k) && values[k]
  const subject = [on('courier') && values.courier, on('vehicle') && values.vehicle.toLowerCase()].filter(Boolean)

  let period = null
  if (on('month')) period = MONTHS[Number(values.month) - 1]
  else if (on('quarter')) period = `Q${values.quarter}`
  if (on('year')) period = period ? `${period} ${values.year}` : values.year

  return (
    <p className="scope">
      Showing{' '}
      {subject.length ? <strong>{subject.join(' ')} deliveries</strong> : 'all deliveries'}
      {on('age_band') && (
        <>
          {' '}by riders aged <strong>{values.age_band}</strong>
        </>
      )}
      {on('size_group') && (
        <>
          , <strong>{values.size_group.toLowerCase()} orders</strong> only
        </>
      )}
      {period ? (
        <>
          , in <strong>{period}</strong>
        </>
      ) : (
        ', across the full year of data'
      )}
      .
    </p>
  )
}
