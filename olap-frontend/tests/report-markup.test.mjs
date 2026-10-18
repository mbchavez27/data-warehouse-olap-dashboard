// Renders the real report components and asserts on the markup that comes out.
//
// There is no browser in CI and no DOM to click, so this renders each view
// state on the server: the component's useState defaults are replaced with a
// read from tests/support/reportState.js, and its data hook is replaced with
// tests/support/useReport-mock.js. That means it needs no database and no
// server, and the rows it renders are the sample rows that
// tests/contracts.test.mjs already holds to each query's own columns.
//
// Expectations are computed from the rows the render was given wherever a
// claim is about a value (a total, a busiest label, a deviation), so this
// checks the component's arithmetic rather than restating a fixture. Claims
// about wording and structure stay literal.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'

import { compact, dec1, pct } from '../src/lib/format.js'
import { chartKeys } from '../src/lib/chartKeys.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const support = path.join(here, 'support')

// The initial state of every useState in the component, replaced with a read
// from the test seam. An unmatched patch is an error, so a refactor fails here
// instead of quietly testing the default view.
const PATCHES = [
  ["useState('rollup')", "useState(initialState().view ?? 'rollup')"],
  ["useState('month')", "useState(initialState().grain ?? 'month')"],
  ["useState('per_day')", "useState(initialState().measure ?? 'per_day')"],
  ["useState('within')", "useState(initialState().colour ?? 'within')"],
  ["useState('busiest')", "useState(initialState().sort ?? 'busiest')"],
  ["useState('10')", "useState(initialState().topN ?? '10')"],
  [
    'useState(() => emptyFilters(ALL_FILTERS))',
    'useState(() => ({ ...emptyFilters(ALL_FILTERS), ...(initialState().filters ?? {}) }))',
  ],
]

// Bundle the report and its imports into one file: the data hook becomes the
// sample rows, and the component's useState defaults become the test's.
const buildHarness = (patches) =>
  build({
    entryPoints: [path.join(support, 'render.jsx')],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    jsx: 'automatic',
    write: false,
    logLevel: 'silent',
    plugins: [
      {
        name: 'report-markup',
        setup(plugin) {
          plugin.onResolve({ filter: /useReport\.js$/ }, () => ({ path: path.join(support, 'useReport-mock.js') }))
          plugin.onLoad({ filter: /DemandCalendarReport\.jsx$/ }, (args) => {
            let source = readFileSync(args.path, 'utf8')
            for (const [from, to] of patches) {
              if (!source.includes(from)) throw new Error(`the state patch matched nothing: ${from}`)
              source = source.replace(from, to)
            }
            return {
              contents: `import { initialState } from ${JSON.stringify(path.join(support, 'reportState.js'))}\n${source}`,
              loader: 'jsx',
            }
          })
        },
      },
    ],
  })

const dir = await mkdtemp(path.join(tmpdir(), 'report-markup-'))
const entry = path.join(dir, 'render.cjs')
await writeFile(entry, (await buildHarness(PATCHES)).outputFiles[0].text)
const harness = createRequire(import.meta.url)(entry)

// ---------- reading the rendered markup ----------

const text = (s) => s.replace(/<[^>]+>/g, '')
const rowsIn = (html) => html.split('<tr').length - 2 // the header row is not data
const stopsIn = (html) => (html.match(/<li class="route-stop/g) ?? []).length

function figure(html, label) {
  const match = html.match(new RegExp(`<dt>${label}</dt><dd[^>]*>(.*?)</dd>`, 's'))
  return match ? text(match[1]) : null
}

function figureSub(html, label) {
  const match = html.match(new RegExp(`<dt>${label}</dt><dd[^>]*>.*?</dd><dd[^>]*>(.*?)</dd>`, 's'))
  return match ? text(match[1]) : null
}

function scopeLine(html) {
  const match = html.match(/<p class="scope">(.*?)<\/p>/s)
  return match ? text(match[1]) : null
}

// The y-axis labels (right-aligned chart-axis text), as numbers.
function axisValues(html) {
  return [...html.matchAll(/class="chart-axis" text-anchor="end">([^<]+)</g)].map((m) => Number(m[1].replace(/,/g, '')))
}

function chartLegend(html) {
  const match = html.match(/<ul class="chart-legend">(.*?)<\/ul>/s)
  return match ? text(match[1]) : ''
}

// The component's documented label for one day of a date column ("14 Mar 2025").
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function dayLabel(date) {
  const [year, month, day] = String(date).slice(0, 10).split('-')
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`
}

const busiestOf = (rows, key) => rows.reduce((a, b) => (!a || Number(b[key]) > Number(a[key]) ? b : a), null)
const quietestOf = (rows, key) => rows.reduce((a, b) => (!a || Number(b[key]) < Number(a[key]) ? b : a), null)
const spreadOf = (busiest, quietest, key) =>
  (100 * (Number(busiest[key]) - Number(quietest[key]))) / Number(quietest[key])

// ---------- the cases ----------

const VIEW_LEVEL = { rollup: 'rollup', trend: 'trend', weekday: 'weekday_pivot', busiest: 'busiest_days' }

// The filter keys each view is allowed to send (only its own reach the API).
const VIEW_PARAMS = {
  rollup: ['day_type', 'payday', 'size_group', 'vehicle', 'year'],
  trend: ['day_type', 'level', 'month', 'payday', 'quarter', 'size_group', 'vehicle', 'year'],
  weekday: ['payday', 'quarter', 'size_group', 'vehicle', 'year'],
  busiest: ['day_type', 'month', 'payday', 'quarter', 'size_group', 'sort', 'top_n', 'vehicle', 'year'],
}

// One unconstrained render per view, so the pinned cases can show that the
// filter narrowed the list rather than just repeating the row count.
const widths = {}
for (const view of Object.keys(VIEW_LEVEL)) {
  harness.setInitialState({ view })
  harness.render()
  widths[view] = harness.lastRequest().rows.length
}

const CASES = [
  {
    name: 'rollup',
    state: { view: 'rollup' },
    checks({ html, rows }) {
      const months = rows.filter((r) => r.hierarchy_level === 'month')
      const grand = rows.find((r) => r.hierarchy_level === 'all')
      const busiest = busiestOf(months, 'orders_per_day')
      const quietest = quietestOf(months, 'orders_per_day')
      const year = rows.find((r) => r.hierarchy_level === 'year')
      const quarter = rows.find((r) => r.hierarchy_level === 'quarter')
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['month rows are indented deepest', html.includes(`cell-strong hier-2">${busiest.month_name} ${busiest.year}`)],
        ['quarter rows are indented one step', html.includes(`cell-strong hier-1">Q${quarter.quarter} ${quarter.year}`)],
        ['year rows sit at the margin', html.includes(`class="cell-strong">${year.year}<`)],
        ['grand total row', html.includes('cell-strong">All dates')],
        ['the total row is styled and not clickable', html.includes('is-total') && html.includes('is-clickable')],
        ['share column', html.includes('Share of orders')],
        ['orders per day column', html.includes('Orders per day')],
        ['grand orders figure', figure(html, 'Orders delivered') === compact(grand.orders), figure(html, 'Orders delivered')],
        [
          'grand orders per day figure',
          figure(html, 'Orders per day') === dec1(grand.orders_per_day),
          figure(html, 'Orders per day'),
        ],
        [
          'month spread figure',
          figure(html, 'Busiest month over the quietest') === `+${dec1(spreadOf(busiest, quietest, 'orders_per_day'))}%`,
          figure(html, 'Busiest month over the quietest'),
        ],
        [
          'the spread names the months it compares',
          figureSub(html, 'Busiest month over the quietest') ===
            `${busiest.month_name} ${busiest.year} against ${quietest.month_name} ${quietest.year}`,
          figureSub(html, 'Busiest month over the quietest'),
        ],
        ['one breadcrumb stop', stopsIn(html) === 1, String(stopsIn(html))],
        ['no ignored-filter note when nothing is hidden', !html.includes('does not apply')],
        ['legend keys the bold subtotals', html.includes('Bold rows = the quarter, year and overall subtotals')],
        ['note explains the drill', html.includes('Click a period to open it in the trend view')],
        ['drill hint on the row', html.includes('title="Open this period in the trend view"')],
      ]
    },
  },
  {
    name: 'rollup-pinned',
    state: { view: 'rollup', filters: { year: '2024', quarter: '4', month: '12' } },
    checks({ html, rows, request }) {
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['the year filter narrowed the sample', rows.length < widths.rollup, `${rows.length} of ${widths.rollup}`],
        ['the year reached the request', request.params.year === '2024'],
        [
          'the level did not send the quarter or month it ignores',
          !('quarter' in request.params) && !('month' in request.params),
        ],
        ['two breadcrumb stops', stopsIn(html) === 2, String(stopsIn(html))],
        ['breadcrumb shows the year', html.includes('>2024<')],
        ['hidden quarter filter is called out', html.includes('The quarter and month filters do not apply at this level.')],
        ['scope names only the year it can apply', scopeLine(html) === 'Showing all deliveries, in 2024.', scopeLine(html)],
        ['the year filter is marked active', html.includes('is-active')],
      ]
    },
  },
  {
    name: 'trend-month',
    state: { view: 'trend', grain: 'month' },
    checks({ html, rows, request }) {
      const busiest = busiestOf(rows, 'orders_per_day')
      const quietest = quietestOf(rows, 'orders_per_day')
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['the grain reached the request', request.params.level === 'month'],
        ['no calendar at month grain', !html.includes('class="cal"')],
        ['chart with an area and a line', html.includes('chart-area') && html.includes('chart-line')],
        ['a dashed moving-average line', html.includes('chart-line is-dashed')],
        [
          'chart legend names both series',
          chartLegend(html).includes('Orders per day') && chartLegend(html).includes('7-period average'),
          chartLegend(html).trim(),
        ],
        ['period labels are read back', html.includes(rows[0].period_label), rows[0].period_label],
        ['bar cells for the period totals', html.includes('bar-cell')],
        [
          'trend columns',
          ['Period', 'Days', 'Orders per day', 'Change vs previous', '7-period average', 'Units'].every((h) =>
            html.includes(h),
          ),
        ],
        ['first period has no change versus previous', rows[0].change_vs_previous_pct === null && html.includes('>–<')],
        ['busiest period figure', figure(html, 'Busiest period') === busiest.period_label, figure(html, 'Busiest period')],
        [
          'quietest period figure',
          figure(html, 'Quietest period') === quietest.period_label,
          figure(html, 'Quietest period'),
        ],
        ['bar legend', html.includes('Bar length = orders')],
        ['arrow legend', html.includes('up or down on the period before')],
        [
          'the chart reads from the keyboard',
          /<svg[^>]*aria-label="[^"]*arrow keys[^"]*"[^>]*tabindex="0"/.test(html) && html.includes('aria-live="polite"'),
        ],
        [
          'the less obvious headers explain themselves',
          ['Days', 'Orders per day', 'Change vs previous', '7-period average'].every((h) =>
            html.includes(`class="th-sort th-hint">${h}<`),
          ),
        ],
        [
          'every header sorts, in the query order until clicked',
          (html.match(/class="th-sort/g) ?? []).length === 7 && !html.includes('aria-sort'),
        ],
        [
          'every change carries an arrow in its direction',
          (html.match(/change is-up/g) ?? []).length === rows.filter((r) => Number(r.change_vs_previous_pct) > 0).length &&
            (html.match(/change is-down/g) ?? []).length === rows.filter((r) => Number(r.change_vs_previous_pct) < 0).length,
        ],
        [
          'y-axis gridlines sit on round values',
          axisValues(html).length >= 3 && axisValues(html).every((v) => v % 10 === 0),
          axisValues(html).join(', '),
        ],
        ['one breadcrumb stop', stopsIn(html) === 1, String(stopsIn(html))],
      ]
    },
  },
  {
    name: 'trend-month-orders',
    state: { view: 'trend', grain: 'month', measure: 'orders' },
    checks({ html }) {
      return [
        ['no moving average for total orders', !chartLegend(html).includes('7-period average'), chartLegend(html).trim()],
        ['chart still renders', html.includes('chart-line')],
        ['no dashed line', !html.includes('is-dashed')],
      ]
    },
  },
  {
    name: 'trend-day',
    state: { view: 'trend', grain: 'day' },
    checks({ html, rows }) {
      const busiest = busiestOf(rows, 'orders_per_day')
      return [
        [
          'the daily table sits closed under the calendar',
          /<details class="table-details"><summary>Show the daily numbers as a table/.test(html) &&
            !html.includes('<details class="table-details" open') &&
            rowsIn(html) === rows.length,
          `${rowsIn(html)} of ${rows.length}`,
        ],
        ['the calendar is the day view', html.includes('class="cal"')],
        ['one cell per day in the slice', (html.match(/cal-cell/g) ?? []).length === rows.length, `${rows.length} days`],
        ['calendar has a colour scale', html.includes('cal-scale') && html.includes('Less') && html.includes('More')],
        ['chart above the calendar too', html.includes('class="chart"')],
        ['note points at the calendar and the table', html.includes('open the daily table under it')],
        [
          'busiest period is a real date',
          figure(html, 'Busiest period') === dayLabel(busiest.period_start),
          figure(html, 'Busiest period'),
        ],
        ['no panel legend at day grain', !html.includes('role="group" aria-label="Legend"')],
      ]
    },
  },
  {
    name: 'trend-week',
    state: { view: 'trend', grain: 'week' },
    checks({ html, rows }) {
      const labels = rows.map((r) => r.period_label)
      const duplicates = labels.length - new Set(labels).size
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        [
          'the slice repeats a week that straddles a quarter',
          duplicates > 0,
          `${rows.length} rows, ${new Set(labels).size} weeks`,
        ],
        ['note explains the duplicate week', html.includes('A week that crosses a quarter boundary appears once for each quarter')],
      ]
    },
  },
  {
    name: 'trend-year',
    state: { view: 'trend', grain: 'year', measure: 'orders' },
    checks({ html, rows }) {
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['no chart legend for two periods', !html.includes('chart-legend')],
        ['note stays quiet about the dashed line', !html.includes('The dashed line')],
      ]
    },
  },
  {
    name: 'trend-pinned',
    state: {
      view: 'trend',
      grain: 'day',
      filters: { year: '2024', quarter: '4', month: '12', day_type: 'weekend', payday: 'yes' },
    },
    checks({ html, rows, request }) {
      const scope = scopeLine(html) ?? ''
      return [
        [
          'one day in the slice, its table closed under the chart',
          html.includes('</svg>') && html.includes(`as a table (${rows.length} ${rows.length === 1 ? 'day' : 'days'})`),
          `${rows.length} rows`,
        ],
        ['the pinned filters reached the request', request.params.day_type === 'weekend' && request.params.payday === 'yes'],
        [
          'scope names weekends and paydays',
          scope.includes('weekends') && scope.includes('paydays') && scope.includes('December 2024'),
          scope,
        ],
        ['four breadcrumb stops', stopsIn(html) === 4, String(stopsIn(html))],
        [
          'breadcrumb rolls back through the hierarchy',
          ['All dates', '>2024<', '>Q4<', '>Dec 2024<'].every((label) => html.includes(label)),
        ],
        ['a single calendar cell', (html.match(/cal-cell/g) ?? []).length === rows.length, `${rows.length} cells`],
      ]
    },
  },
  {
    name: 'weekday',
    state: { view: 'weekday' },
    checks({ html, rows }) {
      const months = rows.filter((r) => !r.is_total)
      const total = rows.find((r) => r.is_total)
      const days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
      const ranked = [...days.map((k) => ({ key: k, value: Number(total[k]) }))].sort((a, b) => b.value - a.value)
      const gap = (100 * (ranked[0].value - ranked[ranked.length - 1].value)) / ranked[ranked.length - 1].value
      const names = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' }
      const belowAverage = rows.flatMap((r) =>
        days.filter((k) => r[k] !== null && r[k] !== undefined && Number(r[k]) < Number(r.all_days)),
      )
      return [
        ['13 months plus a total row', rowsIn(html) === rows.length, `${months.length} months + 1 total`],
        [
          'weekday columns',
          ['>Mon<', '>Tue<', '>Wed<', '>Thu<', '>Fri<', '>Sat<', '>Sun<'].every((d) => html.includes(d)),
        ],
        [
          'cells are static, not drills',
          html.includes('heat-cell is-static') && !html.includes('<button type="button" class="heat-cell"'),
        ],
        ['the total row stands out', html.includes('is-total') && html.includes('cell-strong">All months')],
        ['all days column', html.includes('All days')],
        ['busiest weekday figure', figure(html, 'Busiest weekday') === names[ranked[0].key], figure(html, 'Busiest weekday')],
        [
          'the spread figure is the total row spread',
          figure(html, 'Busiest over the quietest') === `+${dec1(gap)}%`,
          figure(html, 'Busiest over the quietest'),
        ],
        ['colours against its month by default', html.includes('aria-checked="true" class="is-on">Against its month')],
        [
          'every below-average cell takes the below tone',
          (html.match(/is-below/g) ?? []).length === belowAverage.length,
          `${belowAverage.length} cells below their month's average`,
        ],
        ['diverging legend', html.includes('legend-diverge') && html.includes('blue busier, orange quieter')],
        ['no-delivery glyph legend', html.includes('No deliveries in that month and weekday')],
        ['note explains the grain', html.includes('Each cell is the average orders per day')],
        ['note reads the colour as within the month', html.includes("ran above that month&#x27;s average")],
      ]
    },
  },
  {
    name: 'weekday-across',
    state: { view: 'weekday', colour: 'across' },
    checks({ html }) {
      return [
        ['across months is selected', html.includes('aria-checked="true" class="is-on">Across months')],
        ['no cell takes the below tone', !html.includes('is-below')],
        ['heat legend', html.includes('legend-heat') && html.includes('darker means busier')],
        ['note reads the colour across the table', html.includes('against the busiest one in the table')],
      ]
    },
  },
  {
    name: 'weekday-pinned',
    state: { view: 'weekday', filters: { year: '2025', quarter: '1', month: '3', day_type: 'weekend' } },
    checks({ html, rows, request }) {
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['the quarter filter narrowed the sample', rows.length < widths.weekday, `${rows.length} of ${widths.weekday}`],
        ['the quarter reached the request', request.params.quarter === '1'],
        [
          'the level did not send the month or day type it ignores',
          !('month' in request.params) && !('day_type' in request.params),
        ],
        ['the month filter is not offered', !html.includes('class="filter-label">Month<')],
        ['the day-type filter is not offered', !html.includes('class="filter-label">Day type<')],
        ['the quarter filter is offered', html.includes('class="filter-label">Quarter<')],
        [
          'hidden filters are called out',
          html.includes('The month and day type filters do not apply at this level.'),
        ],
        ['scope names only what applies', scopeLine(html) === 'Showing all deliveries, in Q1 2025.', scopeLine(html)],
      ]
    },
  },
  {
    name: 'busiest',
    state: { view: 'busiest', sort: 'busiest', topN: '10', filters: { year: '2025' } },
    checks({ html, rows, request }) {
      const top = rows[0]
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['the sort and size reached the request', request.params.sort === 'busiest' && request.params.top_n === '10'],
        [
          'every column',
          ['Rank', 'Date', 'Day', 'Orders', 'Versus the average day', 'Units', 'Riders', 'Orders per rider'].every((h) =>
            html.includes(h),
          ),
        ],
        ['the top day is named', html.includes(dayLabel(top.date)), dayLabel(top.date)],
        ['a plus signed deviation, arrowed up', /▲<\/span> \+\d+\.\d%</.test(html)],
        [
          'the peak deviation is the top row, a little over the average',
          html.includes(`+${pct(top.vs_average_pct)}`) && Number(top.vs_average_pct) > 0 && Number(top.vs_average_pct) < 15,
          `+${pct(top.vs_average_pct)}`,
        ],
        ['legend keys the deviation column', html.includes('compares a day with the average day')],
        ['note explains the ranking', html.includes('Ranked from every day in the slice')],
      ]
    },
  },
  {
    name: 'busiest-quietest',
    state: { view: 'busiest', sort: 'quietest', topN: '20' },
    checks({ html, rows }) {
      return [
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['quietest first is selected', html.includes('aria-checked="true" class="is-on">Quietest first')],
        ['top 20 is selected', html.includes('aria-checked="true" class="is-on">Top 20')],
        ['negative deviations, arrowed down', /▼<\/span> -\d+\.\d%</.test(html)],
        ['no up arrows among the quietest days', !html.includes('change is-up')],
        ['the top row is the quietest day', rows.every((r) => Number(r.vs_average_pct) < 0)],
        ['caption follows the sort', html.includes('Quietest days')],
      ]
    },
  },
]

test('the harness renders the sample rows through the real components', () => {
  assert.deepEqual(Object.keys(widths).sort(), ['busiest', 'rollup', 'trend', 'weekday'])
  for (const [view, width] of Object.entries(widths)) assert.ok(width > 0, `${view} rendered ${width} rows`)
})

for (const testCase of CASES) {
  test(testCase.name, async (t) => {
    harness.setInitialState(testCase.state)
    const html = harness.render()
    const request = harness.lastRequest()
    const rows = request.rows

    const common = [
      ['nothing renders as undefined', !html.includes('undefined')],
      ['nothing renders as NaN', !html.includes('NaN')],
      ['no [object Object]', !html.includes('[object Object]')],
      ['renders the scope sentence', scopeLine(html) !== null, scopeLine(html)],
      ['renders the panel', html.includes('class="panel"')],
      ['renders the export button', html.includes('Export')],
      ['renders the view switch', html.includes('aria-label="View"')],
      ['reads the level this view owns', request.level === VIEW_LEVEL[testCase.state.view], request.level],
      [
        'requests only the filters this view applies',
        Object.keys(request.params).sort().join() === VIEW_PARAMS[testCase.state.view].join(),
        Object.keys(request.params).sort().join(),
      ],
    ]

    for (const [name, passed, detail] of [...common, ...testCase.checks({ html, rows, request })]) {
      await t.test(name, () => {
        assert.ok(passed, `${testCase.name}: ${name}${detail ? ` — ${detail}` : ''}`)
      })
    }
  })
}

test('a chart steps through its points from the keyboard', () => {
  let current = null
  const set = (next) => {
    current = typeof next === 'function' ? next(current) : next
  }
  const press = (key) => {
    let prevented = false
    chartKeys(5, current, set).onKeyDown({ key, preventDefault: () => (prevented = true) })
    return prevented
  }
  chartKeys(5, current, set).onFocus()
  assert.equal(current, 0, 'focus shows the first point')
  press('ArrowRight')
  press('ArrowRight')
  assert.equal(current, 2)
  press('ArrowLeft')
  assert.equal(current, 1)
  press('End')
  press('ArrowRight')
  assert.equal(current, 4, 'stops at the last point')
  press('Home')
  press('ArrowLeft')
  assert.equal(current, 0, 'stops at the first point')
  assert.equal(press('Tab'), false, 'other keys pass through, so Tab still leaves the chart')
  press('Escape')
  assert.equal(current, null, 'Escape hides the readout')
  chartKeys(5, 3, set).onBlur()
  assert.equal(current, null, 'leaving the chart clears it')
})

test('sorting a table keeps its totals pinned and its blanks last', () => {
  const rows = [
    { name: 'All', n: '60', is_total: true },
    { name: 'b', n: '9' },
    { name: 'a', n: null },
    { name: 'c', n: '10' },
    { name: 'Subtotal', n: '19', is_total: true },
  ]
  const isTotal = (r) => r.is_total
  const names = (sorted) => sorted.map((r) => r.name).join(' ')
  const n = { key: 'n' }
  // NUMERIC arrives as strings, so "10" must sort above "9", not below it.
  assert.equal(names(harness.sortRows(rows, n, 'desc', isTotal)), 'All c b a Subtotal')
  assert.equal(names(harness.sortRows(rows, n, 'asc', isTotal)), 'All b c a Subtotal')
  assert.equal(names(harness.sortRows(rows, { key: 'name' }, 'asc', isTotal)), 'All a b c Subtotal')
  // sortValue sorts a label by something else, e.g. a period by its start date.
  const byStart = { key: 'label', sortValue: (r) => r.start }
  const periods = [{ label: 'April', start: '2025-04-01' }, { label: 'January', start: '2025-01-01' }]
  assert.equal(harness.sortRows(periods, byStart, 'asc').map((r) => r.label).join(' '), 'January April')
  assert.equal(names(rows), 'All b a c Subtotal', 'the input order is left alone')
})

test('a component that renames its state literal fails the harness instead of passing', async () => {
  // The guard the patch list depends on: an unmatched literal throws while
  // bundling, so a refactor cannot leave the cases exercising the default view.
  await assert.rejects(buildHarness([...PATCHES, ["useState('rollup-view')", 'x']]), /the state patch matched nothing/)
})
