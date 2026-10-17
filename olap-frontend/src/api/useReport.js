import { useEffect, useState } from 'react'
import { fetchReport } from './client.js'

// Loads one report level. Rows from the previous request stay on screen while
// the next one loads, but only if they belong to the same level (different
// levels return different columns).
export function useReport(report, level, params) {
  const id = `${report}/${level}`
  const paramsKey = JSON.stringify(params)
  const [state, setState] = useState({ id: null, rows: [], loading: true, error: null })

  useEffect(() => {
    const controller = new AbortController()
    setState((s) => ({ ...s, loading: true, error: null }))
    fetchReport(report, level, JSON.parse(paramsKey), { signal: controller.signal })
      .then((rows) => setState({ id, rows, loading: false, error: null }))
      .catch((err) => {
        if (err.name === 'AbortError') return
        setState({ id, rows: [], loading: false, error: err.message || 'The report could not be loaded.' })
      })
    return () => controller.abort()
  }, [report, level, id, paramsKey])

  return {
    rows: state.id === id ? state.rows : [],
    loading: state.loading || state.id !== id,
    error: state.error,
  }
}
