// Diffs src/api/contracts.js against the running API.
//
// `npm test` proves the sample data matches the committed contract. This
// proves the contract matches the warehouse, which CI cannot: the source
// archive is not in the repository, so CI cannot build the warehouse. Run it
// after an intentional query change, or before a demo.
//
//   npm run check:contracts [-- --base http://localhost:8080]
//
// Writes evidence/contract-check.json and exits non-zero on any difference.
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { CONTRACTS } from '../src/api/contracts.js'
import { MOCKED_LEVELS, mockReport } from '../src/api/mock.js'

const args = process.argv.slice(2)
const base =
  (args.includes('--base') ? args[args.indexOf('--base') + 1] : null) ??
  process.env.API_BASE ??
  'http://localhost:8080'

const startedAt = new Date()
const checks = {}
const live = {}

// Compared as a set: the API serialises a row as a JSON object, and Go writes
// map keys in sorted order, so the response never carries the SQL's column
// order. The contract keeps that order for documentation.
const check = (name, expected, actual) => {
  const left = [...expected].sort()
  const right = [...actual].sort()
  const same = left.length === right.length && left.every((value, i) => value === right[i])
  checks[name] = { expected: left, actual: right, passed: same }
  return same
}

const catalog = await fetch(`${base}/api/reports`)
if (!catalog.ok) throw new Error(`GET ${base}/api/reports answered ${catalog.status}`)
const body = await catalog.json()
const reports = body.reports ?? body

// Every path the dashboard can ask for, so a renamed or added level shows up.
const paths = []
for (const report of reports) {
  for (const level of report.levels ?? []) {
    const declared = (level.columns ?? []).map((column) => (typeof column === 'string' ? column : column.name))
    for (const id of [level.id, ...(level.aliases ?? [])]) paths.push({ path: `${report.id}/${id}`, declared })
  }
}

for (const { path: level, declared } of paths.sort((a, b) => a.path.localeCompare(b.path))) {
  const response = await fetch(`${base}/api/reports/${level}`)
  if (!response.ok) {
    checks[level] = { expected: declared, actual: [`HTTP ${response.status}`], passed: false }
    continue
  }
  const payload = await response.json()
  const rows = Array.isArray(payload) ? payload : payload.rows ?? []
  live[level] = rows
  const returned = rows.length ? Object.keys(rows[0]) : []

  // The contract has to match what the query actually returns.
  if (CONTRACTS[level]) check(level, CONTRACTS[level], returned)
  // And the API's own declaration has to match it too (catalog drift).
  check(`${level} (declared)`, declared, returned)
}

// The contract pins names, not types, so a query that starts returning a
// NUMERIC as a string (or a boolean as "t") would slip past it and only show up
// as a cell formatting oddly. Compare the value types the sample data produces
// with the ones the warehouse sends.
const valueTypes = (rows, column) => {
  const types = new Set()
  for (const row of rows) {
    const value = row[column]
    types.add(value === null || value === undefined ? 'null' : typeof value)
  }
  return [...types].sort().join('|')
}
const typed = (rows, columns) => columns.map((column) => `${column}:${valueTypes(rows, column)}`).sort()

for (const level of MOCKED_LEVELS) {
  const [report, name] = level.split('/')
  const columns = CONTRACTS[level] ?? []
  const sample = mockReport(report, name, {})
  const warehouse = live[level] ?? []
  checks[`${level} value types`] = {
    expected: typed(sample, columns),
    actual: typed(warehouse, columns),
    passed: sample.length > 0 && warehouse.length > 0 && typed(sample, columns).join() === typed(warehouse, columns).join(),
  }
}

// The sample data is only as trustworthy as its coverage.
const uncovered = MOCKED_LEVELS.filter((level) => !CONTRACTS[level])
checks['every mocked level is in the contract'] = {
  expected: MOCKED_LEVELS,
  actual: MOCKED_LEVELS.filter((level) => CONTRACTS[level]),
  passed: uncovered.length === 0,
}

const failed = Object.entries(checks).filter(([, result]) => !result.passed).map(([name]) => name)
const finishedAt = new Date()

for (const { path: level } of paths) {
  const columns = checks[level]?.passed ?? checks[`${level} (declared)`]?.passed
  const types = checks[`${level} value types`]
  console.log(`  ${columns ? 'ok  ' : 'FAIL'} ${level}${types ? ` — value types ${types.passed ? 'ok' : 'FAIL'}` : ''}`)
}
if (failed.length) {
  console.log('\nDifferences:')
  for (const name of failed) {
    const { expected, actual } = checks[name]
    console.log(`  ${name}\n    contract: ${expected.join(', ')}\n    live:     ${actual.join(', ')}`)
  }
}

const evidence = {
  schemaVersion: 1,
  generatedAt: startedAt.toISOString(),
  command: 'npm run check:contracts',
  api: { base, reports: reports.length, levels: paths.length },
  criteria:
    'For every report level the dashboard can request, the committed column contract in olap-frontend/src/api/contracts.js and the API catalog both list the same columns the query returns (compared as a set: Go serialises a row as a JSON object with sorted keys, so the response carries no column order); every level served by the sample data has a contract; and in that sample data each column carries the same value types the warehouse sends.',
  levels: Object.fromEntries(
    paths.map(({ path: level }) => [
      level,
      {
        contractMatchesResponse: checks[level]?.passed ?? null,
        catalogMatchesResponse: checks[`${level} (declared)`]?.passed ?? null,
        valueTypesMatch: checks[`${level} value types`]?.passed ?? null,
      },
    ]),
  ),
  checks,
  failedChecks: failed,
  durationMs: finishedAt - startedAt,
  passed: failed.length === 0,
}

const target = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'evidence', 'contract-check.json')
await mkdir(path.dirname(target), { recursive: true })
await writeFile(target, `${JSON.stringify(evidence, null, 2)}\n`)

console.log(
  `\n${paths.length} levels checked in ${evidence.durationMs} ms — ${evidence.passed ? 'contracts match the warehouse' : `${failed.length} checks failed`}`,
)
console.log(`Evidence: ${path.relative(process.cwd(), target)}`)
process.exit(evidence.passed ? 0 : 1)
