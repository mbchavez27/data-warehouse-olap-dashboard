import { mockReport } from '../../src/api/mock.js'
import { recordRequest } from './reportState.js'

// Stands in for src/api/useReport.js, so a render is synchronous and needs no
// server. The rows come from the sample builders, which tests/contracts.test.mjs
// already holds to each query's own columns.
export function useReport(report, level, params) {
  const rows = mockReport(report, level, params)
  recordRequest({ report, level, params, rows })
  return { rows, loading: false, error: null }
}
