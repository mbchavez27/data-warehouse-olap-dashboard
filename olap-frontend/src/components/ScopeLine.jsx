// One sentence that says exactly which slice of the data is on screen, e.g.
// "Showing JNT motorcycle deliveries, heavy orders only, in Q1 2025." or
// "Showing all deliveries, weekends only, paydays only, in December 2024."
// `values` = filters plus anything pinned by the drill path; `keys` = the
// filters that apply at the current level; `noun` names what is being shown
// ("deliveries" for R1/R2, "customers" for R3). Only keys present in `keys`
// are ever mentioned, so a report stays quiet about dimensions it ignores.
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December']

export default function ScopeLine({ values, keys, noun = 'deliveries' }) {
  const on = (k) => keys.includes(k) && values[k]
  const subject = [on('courier') && values.courier, on('vehicle') && values.vehicle.toLowerCase()].filter(Boolean)
  const place = [on('country') && values.country, on('city') && values.city].filter(Boolean)
  const who = on('gender') ? (values.gender === 'F' ? 'female' : 'male') : null

  let period = null
  if (on('month')) period = MONTHS[Number(values.month) - 1]
  else if (on('quarter')) period = `Q${values.quarter}`
  if (on('year')) period = period ? `${period} ${values.year}` : values.year

  return (
    <p className="scope">
      Showing{' '}
      {subject.length ? <strong>{subject.join(' ')} deliveries</strong> : `all ${noun}`}
      {who && (
        <>
          , <strong>{who}</strong> {noun} only
        </>
      )}
      {on('decile') && (
        <>
          , in <strong>value decile {values.decile}</strong>
        </>
      )}
      {place.length ? (
        <>
          , in <strong>{place.join(' · ')}</strong>
        </>
      ) : null}
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
      {on('day_type') && (
        <>
          , <strong>{values.day_type === 'weekend' ? 'weekends' : 'weekdays'}</strong> only
        </>
      )}
      {on('payday') && (
        <>
          , <strong>{values.payday === 'yes' ? 'paydays' : 'non-paydays'}</strong> only
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
