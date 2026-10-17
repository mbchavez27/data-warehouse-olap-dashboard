// Guards the promise src/api/mock.js makes: its sample rows carry exactly the
// columns the matching SQL file returns, and the reports only read columns
// that exist.
//
// Mock mode is the dashboard default, so a stale builder or a renamed query
// column would otherwise show as a blank cell that only a live run or a reader
// would catch. This runs without a warehouse or a browser, so CI can enforce
// it:
//
//   npm test
//
// The one link it cannot see is the SQL itself (the source archive is not in
// the repository, so CI cannot build the warehouse). `npm run check:contracts`
// covers that against a running API.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { mockReport, MOCKED_LEVELS } from '../src/api/mock.js'
import { CONTRACTS } from '../src/api/contracts.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.join(here, '..', 'src')

// Parameters chosen to reach each builder's branches, so the rows are shaped
// under the filters the dashboard actually sends (a grain, a sort, a top-N, a
// drill, all filters at once).
const CASES = {
  'r1/category': [{}, { year: '2025', quarter: '2', vehicle: 'Motorcycle', size_group: 'Heavy' }],
  'r1/product': [
    { category: 'Electronics' },
    { category: 'Electronics', courier: 'JNT', age_band: '30-39', top_n: '25', year: '2024', quarter: '1' },
  ],
  'r2/cube': [{}, { courier: 'JNT', vehicle: 'Motorcycle', year: '2025' }],
  'r2/pivot': [{}, { measure: 'per_rider', year: '2024', quarter: '4' }],
  'r2/rider': [{ top_n: '25' }, { sort: 'quietest', year: '2025', quarter: '2' }],
  'r3/deciles': [{}, { year: '2024', quarter: '1', gender: 'F', country: 'Japan' }],
  'r3/geography': [{ level: 'country' }, { level: 'city', country: 'Japan' }, { gender: 'M', year: '2025', top_n: '30' }],
  'r3/customer': [
    { top_n: '25' },
    { decile: '3', gender: 'F', year: '2024', quarter: '2', country: 'Japan', city: 'Sakai' },
  ],
  'r4/rollup': [{}, { year: '2024', day_type: 'weekend', payday: 'yes', vehicle: 'Bicycle', size_group: 'Light' }],
  'r4/trend': [
    { level: 'year' },
    { level: 'quarter' },
    { level: 'month' },
    { level: 'week' },
    { level: 'day' },
    { level: 'day', year: '2024', quarter: '4', month: '12', day_type: 'weekend', payday: 'yes' },
  ],
  'r4/weekday_pivot': [{}, { year: '2025', quarter: '1', payday: 'yes', vehicle: 'Motorcycle', size_group: 'Heavy' }],
  'r4/busiest_days': [
    { top_n: '10' },
    { sort: 'quietest', top_n: '365' },
    { year: '2025', quarter: '1', month: '3', day_type: 'weekend', payday: 'no', vehicle: 'Car', size_group: 'Heavy' },
  ],
}

// The report components and the report id each one reads.
const REPORT_FILES = {
  ProductCategoryReport: 'r1',
  FleetWorkloadReport: 'r2',
  CustomerValueReport: 'r3',
  DemandCalendarReport: 'r4',
}

// Fields of objects the reports build alongside rows: the `{ name, value }`
// entries the weekday ranking sorts, and the table-column configs. They share
// generic variable names (a, b, c) with real rows, so a read of one is not a
// read of a query column.
const NOT_A_COLUMN = new Set([
  'key', 'label', 'align', 'render', 'csv', 'tip', 'title', 'width', 'value',
  'name', 'text', 'sub', 'short', 'unit',
])

// Variables bound by an array callback, e.g. `.map((r) => r.orders)`. A name
// counts as a row variable when at least one of its reads is a real column,
// which keeps column-config callbacks (`c.key`) out.
function rowVariables(text, columns) {
  const names = new Set()
  for (const match of text.matchAll(
    /\.(?:map|filter|find|findIndex|reduce|some|every|sort|flatMap|forEach)\(\s*\(?\s*([A-Za-z_$][\w$]*)\s*[,)=]/g,
  )) {
    names.add(match[1])
  }
  for (const match of text.matchAll(/for \(const ([A-Za-z_$][\w$]*) of /g)) names.add(match[1])

  const rows = new Set()
  for (const name of names) {
    const reads = [...text.matchAll(new RegExp(`\\b${name}\\.([a-z_][a-z0-9_]*)`, 'g'))].map((m) => m[1])
    if (reads.some((key) => columns.has(key))) rows.add(name)
  }
  return rows
}

test('every level the sample data serves has a generated contract', () => {
  const missing = MOCKED_LEVELS.filter((level) => !CONTRACTS[level])
  assert.deepEqual(missing, [], 'run npm run sync:contracts')
})

for (const level of MOCKED_LEVELS) {
  test(`${level}: sample rows carry exactly the columns their query returns`, () => {
    const [report, name] = level.split('/')
    let seen = 0
    for (const params of CASES[level] ?? [{}]) {
      for (const row of mockReport(report, name, params)) {
        seen += 1
        assert.deepEqual(
          Object.keys(row),
          CONTRACTS[level],
          `${level} with ${JSON.stringify(params)}`,
        )
      }
    }
    assert.ok(seen > 0, `${level} produced no sample rows`)
  })
}

test('the reports only read columns their queries return', () => {
  const problems = []
  for (const [file, report] of Object.entries(REPORT_FILES)) {
    const text = readFileSync(path.join(src, 'reports', `${file}.jsx`), 'utf8')
    const columns = new Set(
      Object.entries(CONTRACTS)
        .filter(([level]) => level.startsWith(`${report}/`))
        .flatMap(([, names]) => names),
    )
    for (const name of rowVariables(text, columns)) {
      for (const match of text.matchAll(new RegExp(`\\b${name}\\.([a-z_][a-z0-9_]*)`, 'g'))) {
        const key = match[1]
        if (!columns.has(key) && !NOT_A_COLUMN.has(key)) problems.push(`${file}: ${name}.${key}`)
      }
    }
  }
  assert.deepEqual(problems, [], 'a report reads a column the SQL does not return')
})

test('every table column is a real column or derives its own value', () => {
  const problems = []
  for (const [file, report] of Object.entries(REPORT_FILES)) {
    const text = readFileSync(path.join(src, 'reports', `${file}.jsx`), 'utf8')
    const columns = new Set(
      Object.entries(CONTRACTS)
        .filter(([level]) => level.startsWith(`${report}/`))
        .flatMap(([, names]) => names),
    )
    for (const object of text.matchAll(/\{[^{}]*\bkey: *'([^']*)'[^{}]*\}/g)) {
      const [whole, key] = object
      if (columns.has(key)) continue
      if (/\brender:/.test(whole) || /\bcsv:/.test(whole)) continue
      problems.push(`${file}: column '${key}' is neither a query column nor derived`)
    }
  }
  assert.deepEqual(problems, [])
})
