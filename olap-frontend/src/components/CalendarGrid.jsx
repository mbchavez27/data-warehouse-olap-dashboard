import Tooltip from './Tooltip.jsx'

// GitHub-style demand calendar: one small cell per day, columns are weeks and
// rows are weekdays, colour intensity is the day's value. Hand-rolled CSS grid,
// no library.
//
//   points  { date: 'YYYY-MM-DD', value, label? }[]  any order; sorted here
//   format  (v) => string
//   title   accessible name
const MS_DAY = 86400000
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const LEVELS = [0, 0.25, 0.5, 0.75, 1]

const toMs = (date) => Date.parse(`${date}T00:00:00Z`)
// 0 = Monday .. 6 = Sunday, so the grid reads top-to-bottom like a calendar.
const weekday = (ms) => (new Date(ms).getUTCDay() + 6) % 7
const heat = (value, max) => Math.round(6 + (max ? (Number(value) || 0) / max : 0) * 50)

export default function CalendarGrid({ points, format = String, title = 'Daily demand' }) {
  if (!points.length) return null

  const days = [...points].sort((a, b) => toMs(a.date) - toMs(b.date))
  const start = toMs(days[0].date)
  const startDow = weekday(start)
  const max = Math.max(0, ...days.map((d) => Number(d.value) || 0))
  const columnOf = (ms) => Math.floor(((ms - start) / MS_DAY + startDow) / 7)
  const weeks = columnOf(toMs(days[days.length - 1].date)) + 1

  // One label per month, spanning from its first week to the next month's.
  const months = []
  for (const day of days) {
    const ms = toMs(day.date)
    const month = new Date(ms).getUTCMonth()
    if (!months.length || months[months.length - 1].month !== month) {
      months.push({ month, label: MONTHS[month], col: columnOf(ms) })
    }
  }
  months.forEach((m, i) => {
    m.span = (i + 1 < months.length ? months[i + 1].col : weeks) - m.col
  })

  return (
    <div className="cal" role="group" aria-label={title}>
      <div className="cal-months" style={{ gridTemplateColumns: `repeat(${weeks}, 1fr)` }}>
        {months
          .filter((m, i) => m.span > 0 || i === months.length - 1)
          .map((m) => (
            <span key={`${m.month}-${m.col}`} style={{ gridColumn: `${m.col + 1} / span ${Math.max(1, m.span)}` }}>
              {m.label}
            </span>
          ))}
      </div>

      <div className="cal-body">
        <ul className="cal-days">
          {WEEKDAYS.map((name, i) => (
            <li key={name}>{i % 2 === 0 ? name : ''}</li>
          ))}
        </ul>
        <div className="cal-grid" style={{ gridTemplateColumns: `repeat(${weeks}, 1fr)` }}>
          {days.map((day) => (
            <Tooltip
              key={day.date}
              className="cal-cell"
              style={{ gridRow: weekday(toMs(day.date)) + 1, gridColumn: columnOf(toMs(day.date)) + 1, '--heat': `${heat(day.value, max)}%` }}
              text={`${day.label ?? day.date}: ${format(day.value)}`}
            />
          ))}
        </div>
      </div>

      <div className="cal-scale">
        <span>Less</span>
        {LEVELS.map((f) => (
          <i key={f} style={{ '--heat': `${heat(f * max, max)}%` }} />
        ))}
        <span>More</span>
      </div>
    </div>
  )
}
