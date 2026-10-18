// One place that knows how the dashboard talks to the Go API.
//
// Every report level maps to one SQL file in olap/queries:
//   GET /api/reports/{report}/{level}?param=value&...
// e.g. /api/reports/r1/category?year=2025&vehicle=Motorcycle
// Parameter names are the same as in the SQL file headers. Filters left on
// "All" are not sent (the SQL treats a missing/empty value as "no filter").
// The response is either a JSON array of rows or { "rows": [...] }, with the
// SQL output column names as keys.

import { mockReport } from './mock.js'

const mode = (import.meta.env.VITE_API_MODE || 'mock').toLowerCase()
export const isMock = mode !== 'live'

const BASE = import.meta.env.VITE_API_BASE || '/api'

export async function fetchReport(report, level, params, { signal } = {}) {
  const sent = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined),
  )

  if (isMock) {
    await new Promise((resolve) => setTimeout(resolve, 200))
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    return mockReport(report, level, sent)
  }

  const query = new URLSearchParams(sent).toString()
  const url = `${BASE}/reports/${report}/${level}${query ? `?${query}` : ''}`
  let res
  try {
    res = await fetch(url, { signal })
  } catch (err) {
    // A network failure surfaces as the browser's bare "Failed to fetch".
    if (err.name === 'AbortError') throw err
    throw new Error("Couldn't reach the report service.")
  }
  if (!res.ok) {
    let message = `The report service answered ${res.status} ${res.statusText}.`
    try {
      const body = await res.json()
      if (body?.error) message = body.error
    } catch {
      // Not JSON. The API always explains its own errors in JSON, so an empty
      // 5xx comes from the /api proxy in front of it: the API is down or
      // restarting, not broken.
      if (res.status >= 500) message = `Couldn't reach the report service (HTTP ${res.status}).`
    }
    throw new Error(message)
  }
  const body = await res.json()
  return Array.isArray(body) ? body : body.rows ?? []
}
