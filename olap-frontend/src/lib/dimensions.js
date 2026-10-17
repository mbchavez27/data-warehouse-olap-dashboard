// Filter definitions shared by every report. Each value matches what the SQL
// files in olap/queries accept; '' means "no filter" for that dimension.

const ALL = { value: '', label: 'All' }
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export const DATA_RANGE = '24 Sep 2024 to 23 Sep 2025'

export const YEAR = {
  key: 'year',
  label: 'Year',
  options: [ALL, { value: '2024', label: '2024' }, { value: '2025', label: '2025' }],
}

export const QUARTER = {
  key: 'quarter',
  label: 'Quarter',
  options: [ALL, ...[1, 2, 3, 4].map((q) => ({ value: String(q), label: `Q${q}` }))],
}

// Months follow the chosen quarter, so the user can't pick "Q1 + August".
export const MONTH = {
  key: 'month',
  label: 'Month',
  getOptions: (values) => {
    const q = Number(values.quarter)
    const months = MONTH_NAMES.map((name, i) => ({ value: String(i + 1), label: name }))
    return [ALL, ...(q ? months.slice((q - 1) * 3, q * 3) : months)]
  },
}

export const VEHICLE = {
  key: 'vehicle',
  label: 'Vehicle',
  options: [ALL, ...['Motorcycle', 'Bicycle', 'Car', 'Trike'].map((v) => ({ value: v, label: v }))],
}

export const SIZE_GROUP = {
  key: 'size_group',
  label: 'Order size',
  options: [ALL, { value: 'Light', label: 'Light orders' }, { value: 'Heavy', label: 'Heavy orders' }],
}

export const COURIER = {
  key: 'courier',
  label: 'Courier',
  options: [ALL, ...['FEDEZ', 'JNT', 'LBCD'].map((c) => ({ value: c, label: c }))],
}

export const AGE_BAND = {
  key: 'age_band',
  label: 'Rider age',
  options: [ALL, ...['18-29', '30-39', '40-49', '50-60'].map((a) => ({ value: a, label: a }))],
}

// Customer slice used by R3 (matches DIM_CUSTOMER.gender).
export const GENDER = {
  key: 'gender',
  label: 'Gender',
  options: [ALL, { value: 'F', label: 'Female' }, { value: 'M', label: 'Male' }],
}

// 1 = the top 10% of customers by value (from R3's deciles level).
export const DECILE = {
  key: 'decile',
  label: 'Value decile',
  options: [ALL, ...[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => ({ value: String(n), label: `Decile ${n}` }))],
}

// Calendar slices used by R4 (match DIM_DATE.isWeekend / isPayDay).
export const DAY_TYPE = {
  key: 'day_type',
  label: 'Day type',
  options: [ALL, { value: 'weekday', label: 'Weekdays' }, { value: 'weekend', label: 'Weekends' }],
}

export const PAYDAY = {
  key: 'payday',
  label: 'Payday',
  options: [ALL, { value: 'yes', label: 'Paydays' }, { value: 'no', label: 'Non-paydays' }],
}

export const emptyFilters = (defs) => Object.fromEntries(defs.map((d) => [d.key, '']))

// Applies one filter change and clears a month that falls outside a new quarter.
export function changeFilter(values, key, value) {
  const next = { ...values, [key]: value }
  if (key === 'quarter' && value && next.month) {
    const q = Math.ceil(Number(next.month) / 3)
    if (q !== Number(value)) next.month = ''
  }
  return next
}

// Abbreviated month name, e.g. 9 -> "Sep"; the same shape as the MONTH options.
export const monthLabel = (month) => MONTH_NAMES[Number(month) - 1] ?? ''

// "Q1 2025", "Mar 2025", "2024", or "the whole year" — used in headings.
export function periodLabel({ year, quarter, month }) {
  const parts = []
  if (month) parts.push(MONTH_NAMES[Number(month) - 1])
  else if (quarter) parts.push(`Q${quarter}`)
  if (year) parts.push(year)
  if (!parts.length) return 'the full year of data'
  if (!year) return `${parts[0]}, both years`
  return parts.join(' ')
}
