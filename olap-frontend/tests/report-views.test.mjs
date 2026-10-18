// Renders R1, R2 and R3 through their real components and asserts on the
// markup, the same way tests/report-markup.test.mjs does for R4.
//
// Each report is bundled with esbuild: its data hook becomes
// tests/support/useReport-mock.js (the sample rows, which
// tests/contracts.test.mjs holds to each query's columns), and its useState
// defaults become reads from tests/support/reportState.js, so a case can open
// any view or drill level without a browser. Where a check is about a value
// (a total, a leader, an average) the expectation is computed from the rows
// that were rendered, so this tests the component's arithmetic, not a fixture.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'

import { compact, num, pct, peso } from '../src/lib/format.js'
import { THEME_KEY, applyTheme, currentTheme, otherTheme } from '../src/lib/theme.js'
import { HOME, NOT_FOUND, routeFromHash } from '../src/lib/route.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const support = path.join(here, 'support')
const reports = path.join(here, '..', 'src', 'reports')

// Each report's useState defaults, replaced with a read from the test seam. An
// unmatched patch fails the build, so a renamed literal can't quietly leave a
// case testing the default view.
const PATCHES = {
  ProductCategoryReport: [
    ['useState(() => emptyFilters(FILTERS))', 'useState(() => ({ ...emptyFilters(FILTERS), ...(initialState().filters ?? {}) }))'],
    ['useState(null)', 'useState(initialState().category ?? null)'],
    ["useState('10')", "useState(initialState().topN ?? '10')"],
  ],
  FleetWorkloadReport: [
    ['useState(() => emptyFilters(FILTERS))', 'useState(() => ({ ...emptyFilters(FILTERS), ...(initialState().filters ?? {}) }))'],
    [
      'useState({ courier: null, vehicle: null })',
      'useState({ courier: null, vehicle: null, ...(initialState().drill ?? {}) })',
    ],
    ["useState('orders')", "useState(initialState().measure ?? 'orders')"],
    ["useState('across')", "useState(initialState().colour ?? 'across')"],
    ["useState('most')", "useState(initialState().sort ?? 'most')"],
    ["useState('20')", "useState(initialState().topN ?? '20')"],
  ],
  CustomerValueReport: [
    ['useState(() => emptyFilters(FILTERS))', 'useState(() => ({ ...emptyFilters(FILTERS), ...(initialState().filters ?? {}) }))'],
    ["useState('deciles')", "useState(initialState().view ?? 'deciles')"],
    ["useState('country')", "useState(initialState().geoLevel ?? 'country')"],
    [
      'useState({ decile: null, country: null, city: null })',
      'useState({ decile: null, country: null, city: null, ...(initialState().drill ?? {}) })',
    ],
    ["useState('20')", "useState(initialState().topN ?? '20')"],
  ],
}

const entrySource = `
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ProductCategoryReport from ${JSON.stringify(path.join(reports, 'ProductCategoryReport.jsx'))}
import FleetWorkloadReport from ${JSON.stringify(path.join(reports, 'FleetWorkloadReport.jsx'))}
import CustomerValueReport from ${JSON.stringify(path.join(reports, 'CustomerValueReport.jsx'))}
import Home from ${JSON.stringify(path.join(here, '..', 'src', 'Home.jsx'))}
import NotFound from ${JSON.stringify(path.join(here, '..', 'src', 'NotFound.jsx'))}
import ErrorBoundary from ${JSON.stringify(path.join(here, '..', 'src', 'components', 'ErrorBoundary.jsx'))}
import ReportStatus from ${JSON.stringify(path.join(here, '..', 'src', 'components', 'ReportStatus.jsx'))}
export { REPORTS } from ${JSON.stringify(path.join(reports, 'index.js'))}
export { setInitialState, lastRequest } from ${JSON.stringify(path.join(support, 'reportState.js'))}
const COMPONENTS = { r1: ProductCategoryReport, r2: FleetWorkloadReport, r3: CustomerValueReport }
export const render = (report) => renderToStaticMarkup(createElement(COMPONENTS[report]))
export const renderHome = () => renderToStaticMarkup(createElement(Home))
export const renderNotFound = (hash) => renderToStaticMarkup(createElement(NotFound, { hash }))
export const renderStatus = (props) => renderToStaticMarkup(createElement(ReportStatus, props))
// Server rendering can't trigger a boundary, so put it in its caught state by hand.
export const renderCrashed = (error) => {
  const boundary = new ErrorBoundary({ children: null })
  boundary.state = ErrorBoundary.getDerivedStateFromError(error)
  return renderToStaticMarkup(boundary.render())
}
`

const buildHarness = (patches) =>
  build({
    stdin: { contents: entrySource, resolveDir: here, loader: 'jsx' },
    bundle: true,
    platform: 'node',
    format: 'cjs',
    jsx: 'automatic',
    write: false,
    logLevel: 'silent',
    plugins: [
      {
        name: 'report-views',
        setup(plugin) {
          plugin.onResolve({ filter: /useReport\.js$/ }, () => ({ path: path.join(support, 'useReport-mock.js') }))
          plugin.onLoad({ filter: /(ProductCategory|FleetWorkload|CustomerValue)Report\.jsx$/ }, (args) => {
            let source = readFileSync(args.path, 'utf8')
            for (const [from, to] of patches[path.basename(args.path, '.jsx')]) {
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

const dir = await mkdtemp(path.join(tmpdir(), 'report-views-'))
const entry = path.join(dir, 'render.cjs')
await writeFile(entry, (await buildHarness(PATCHES)).outputFiles[0].text)
const harness = createRequire(import.meta.url)(entry)

// ---------- reading the rendered markup ----------

const text = (s) =>
  s
    .replace(/<!-- -->/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&')
const rowsIn = (html) => (html.match(/<tbody>(.*?)<\/tbody>/s)?.[1].match(/<tr/g) ?? []).length
const count = (html, needle) => html.split(needle).length - 1
const stopsIn = (html) => count(html, '<li class="route-stop')
const hinted = (html) => [...html.matchAll(/class="th-sort th-hint">([^<]+)</g)].map((m) => m[1])

function figure(html, label) {
  const match = html.match(new RegExp(`<dt>${label}</dt><dd[^>]*>(.*?)</dd>`, 's'))
  return match ? text(match[1]) : null
}

function figureSub(html, label) {
  const match = html.match(new RegExp(`<dt>${label}</dt><dd[^>]*>.*?</dd><dd[^>]*>(.*?)</dd>`, 's'))
  return match ? text(match[1]) : null
}

function chartLegend(html) {
  const match = html.match(/<ul class="chart-legend">(.*?)<\/ul>/s)
  return match ? text(match[1]) : ''
}

const average = (values) => values.reduce((a, b) => a + b, 0) / values.length

// ---------- the cases ----------

const CASES = [
  // ---- R1 ----
  {
    name: 'r1 categories',
    report: 'r1',
    state: {},
    checks({ html, rows, request }) {
      const total = rows.find((r) => r.is_total)
      const detail = rows.filter((r) => !r.is_total)
      return [
        ['reads the category level', request.level === 'category'],
        ['renders every row the query returned', rowsIn(html) === rows.length, `${rowsIn(html)} of ${rows.length}`],
        ['every category drills, the total does not', count(html, 'is-clickable') === detail.length],
        ['units figure is the total row', figure(html, 'Units delivered') === compact(total.units), figure(html, 'Units delivered')],
        ['leading category is the first row', figure(html, 'Leading category') === detail[0].category],
        ['every header sorts', count(html, 'class="th-sort') === 5],
        [
          'the less obvious headers explain themselves',
          ['Rank', 'Units delivered', 'List-price value', 'Share of value'].every((h) => hinted(html).includes(h)),
          hinted(html).join(', '),
        ],
        ['one breadcrumb stop', stopsIn(html) === 1],
        ['no top-N switch before a drill', !html.includes('aria-label="Show"')],
      ]
    },
  },
  {
    name: 'r1 products in a category',
    report: 'r1',
    state: { category: 'Toys', topN: '5' },
    checks({ html, rows, request }) {
      const subtotal = rows.find((r) => r.is_subtotal)
      const products = rows.filter((r) => !r.is_subtotal)
      return [
        ['reads the product level', request.level === 'product'],
        ['the drill and size reached the request', request.params.category === 'Toys' && request.params.top_n === '5'],
        ['renders every row the query returned', rowsIn(html) === rows.length],
        ['the subtotal names its category', html.includes('All Toys products')],
        ['top product is the first row', figure(html, 'Top product') === products[0].product],
        ['units figure is the subtotal', figure(html, 'Toys units delivered') === compact(subtotal.units)],
        ['two breadcrumb stops', stopsIn(html) === 2],
        ['top 5 is selected', html.includes('aria-checked="true" class="is-on">Top 5')],
        ['products do not drill further', !html.includes('is-clickable')],
      ]
    },
  },

  // ---- R2 ----
  {
    name: 'r2 courier x vehicle grid',
    report: 'r2',
    state: {},
    checks({ html, rows, request }) {
      const total = rows.find((r) => r.is_total)
      return [
        ['reads the pivot level', request.level === 'pivot' && request.params.measure === 'orders'],
        ['renders every row the query returned', rowsIn(html) === rows.length],
        ['orders figure is the total row', figure(html, 'Orders delivered') === compact(total.total)],
        ['couriers figure counts the couriers', figure(html, 'Couriers') === String(rows.length - 1)],
        ['across couriers is the default colour', html.includes('aria-checked="true" class="is-on">Across couriers')],
        ['no cell takes the below tone', !html.includes('is-below')],
        ['heat legend', chartLegend(html) === '' && html.includes('darker means more')],
        ['every header sorts', count(html, 'class="th-sort') === 7],
      ]
    },
  },
  {
    name: 'r2 grid against each courier',
    report: 'r2',
    state: { measure: 'per_rider', colour: 'within' },
    checks({ html, rows }) {
      const vehicles = ['motorcycle', 'bicycle', 'car', 'trike']
      const below = rows.flatMap((r) =>
        vehicles.filter((k) => r[k] !== null && r[k] !== undefined && Number(r[k]) < Number(r.total)),
      )
      return [
        ['against its courier is selected', html.includes('aria-checked="true" class="is-on">Against its courier')],
        [
          "every cell under its courier's orders per rider takes the below tone",
          count(html, 'is-below') === below.length,
          `${below.length} cells below`,
        ],
        ['diverging legend', html.includes('legend-diverge') && html.includes('full colour at 10% or more')],
        ['per-rider figure', figure(html, 'Orders per rider') !== null],
      ]
    },
  },
  {
    name: 'r2 one courier by vehicle',
    report: 'r2',
    state: { drill: { courier: 'JNT' } },
    checks({ html, rows, request }) {
      const cells = rows.filter((r) => r.grouping_level === 0)
      const subtotal = rows.find((r) => r.grouping_level === 1)
      return [
        ['reads the cube level for that courier', request.level === 'cube' && request.params.courier === 'JNT'],
        ['one row per vehicle plus the subtotal', rowsIn(html) === cells.length + 1, `${rowsIn(html)}`],
        ['the subtotal row comes last', /All JNT vehicles(?![\s\S]*<tr)/.test(html)],
        ['orders figure is the subtotal', figure(html, 'JNT orders') === compact(subtotal.orders)],
        ['the courier filter is pinned', html.includes('filter is-pinned')],
        ['two breadcrumb stops', stopsIn(html) === 2],
      ]
    },
  },
  {
    name: 'r2 riders',
    report: 'r2',
    state: { drill: { courier: 'JNT', vehicle: 'Motorcycle' }, filters: { size_group: 'Heavy' } },
    checks({ html, rows, request }) {
      const orders = rows.map((r) => Number(r.orders))
      return [
        ['reads the rider level', request.level === 'rider' && request.params.vehicle === 'Motorcycle'],
        ['the order-size filter is not sent', !('size_group' in request.params)],
        ['nor offered', !html.includes('class="filter-label">Size<') && !html.includes('>Order size<')],
        ['renders every row the query returned', rowsIn(html) === rows.length],
        ['one dot per rider listed', count(html, 'class="strip-dot') === rows.length],
        ['the strip labels its band and median', html.includes('Even share (±5%)') && html.includes('>Median<')],
        ['the strip reads from the keyboard', /<svg[^>]*arrow keys[^>]*tabindex="0"/.test(html)],
        [
          'the average covers only the riders listed',
          figure(html, 'Average of those listed') === num(average(orders)) &&
            figureSub(html, 'Average of those listed') === `orders per rider, across the ${rows.length} busiest riders`,
          figureSub(html, 'Average of those listed'),
        ],
        ['days active shows the utilization', html.includes(` · ${pct(rows[0].utilization_pct)}`)],
        [
          'the less obvious headers explain themselves',
          ['Rank', 'Orders', 'Days active', 'Orders per active day', 'Busiest day', 'Busier than'].every((h) =>
            hinted(html).includes(h),
          ),
          hinted(html).join(', '),
        ],
        ['three breadcrumb stops', stopsIn(html) === 3],
      ]
    },
  },

  // ---- R3 ----
  {
    name: 'r3 deciles',
    report: 'r3',
    state: {},
    checks({ html, rows, request }) {
      return [
        ['reads the deciles level', request.level === 'deciles'],
        ['ten deciles', rowsIn(html) === 10 && rows.length === 10],
        ['top decile figure', figure(html, 'Top decile holds') === pct(rows[0].value_share_pct)],
        ['a bar per decile', count(html, 'class="chart-bar') === 10],
        ['the 80% line and its key', html.includes('chart-reference') && chartLegend(html).includes('80% of value')],
        ['the running total says what it adds up', chartLegend(html).includes('decile 1 through that decile')],
        ['the chart reads from the keyboard', /<svg[^>]*arrow keys[^>]*tabindex="0"/.test(html)],
        ['every decile drills', count(html, 'is-clickable') === 10],
        ['every header sorts', count(html, 'class="th-sort') === 7],
      ]
    },
  },
  {
    name: 'r3 geography by country',
    report: 'r3',
    state: { view: 'geography' },
    checks({ html, rows, request }) {
      const countries = rows.filter((r) => r.grouping_level === 1)
      return [
        ['reads the geography level by country', request.level === 'geography' && request.params.level === 'country'],
        ['renders every row the query returned', rowsIn(html) === rows.length],
        ['every country is a drill link', count(html, 'class="link-cell"') === countries.length],
        ['leading country is the first one', figure(html, 'Leading country') === countries[0].location],
        ['the hierarchy keeps its order: no sorting', !html.includes('th-sort')],
        ['the rank header explains itself', html.includes('class="th-hint" tabindex="0">Rank<')],
      ]
    },
  },
  {
    name: 'r3 customers in a decile',
    report: 'r3',
    state: { view: 'customer', drill: { decile: 1 }, topN: '10' },
    checks({ html, rows, request }) {
      const values = rows.map((r) => Number(r.value))
      return [
        ['the decile and size reached the request', request.params.decile === 1 && request.params.top_n === '10'],
        ['renders every row the query returned', rowsIn(html) === rows.length],
        [
          'the average covers only the customers listed',
          figure(html, 'Average of those listed') === peso(average(values)) &&
            figureSub(html, 'Average of those listed') === `across the top ${rows.length} by list-price value`,
          figure(html, 'Average of those listed'),
        ],
        ['top customer is the first row', figure(html, 'Top customer') === rows[0].customer],
        ['the breadcrumb names the decile', html.includes('Value decile 1')],
        ['a gender column with no gender filter', html.includes('>Gender<')],
        ['every header sorts', count(html, 'class="th-sort') > 0],
      ]
    },
  },
]

test('every case reads its own report', () => {
  assert.deepEqual([...new Set(CASES.map((c) => c.report))].sort(), ['r1', 'r2', 'r3'])
})

for (const testCase of CASES) {
  test(testCase.name, async (t) => {
    harness.setInitialState(testCase.state)
    const html = harness.render(testCase.report)
    const request = harness.lastRequest()
    const rows = request.rows

    const common = [
      ['nothing renders as undefined', !html.includes('undefined')],
      ['nothing renders as NaN', !html.includes('NaN')],
      ['no [object Object]', !html.includes('[object Object]')],
      ['reads its own report', request.report === testCase.report],
      ['the query returned rows', rows.length > 0, `${rows.length} rows`],
      ['renders the scope sentence', html.includes('<p class="scope">')],
      ['renders the panel and the export button', html.includes('class="panel"') && html.includes('Export')],
    ]

    for (const [name, passed, detail] of [...common, ...testCase.checks({ html, rows, request })]) {
      await t.test(name, () => {
        assert.ok(passed, `${testCase.name}: ${name}${detail ? ` — ${detail}` : ''}`)
      })
    }
  })
}

test('the home page opens by default and links every report', () => {
  const ids = harness.REPORTS.map((r) => r.id)
  assert.equal(routeFromHash('', ids), HOME, 'no hash opens the home page')
  assert.equal(routeFromHash('#home', ids), HOME)
  assert.equal(routeFromHash('#r9', ids), NOT_FOUND, 'a stale link opens the not-found page, not a report')
  assert.equal(routeFromHash('#oops', ids), NOT_FOUND)
  assert.equal(routeFromHash('#r3', ids), 'r3', 'a report link still opens that report')
  assert.equal(routeFromHash(undefined, ids), HOME)

  const html = harness.renderHome()
  assert.ok(html.includes('class="home-title">Road Runner<'), 'the title')
  assert.ok(html.includes('Last-mile logistics analytics'), 'the subtitle')
  assert.equal(count(html, 'class="home-card"'), harness.REPORTS.length, 'one card per report')
  for (const r of harness.REPORTS) {
    assert.ok(html.includes(`href="#${r.id}" class="home-card"`), `${r.id} has a card linking to it`)
    assert.ok(text(html).includes(r.name) && text(html).includes(r.explore), `${r.id} card names and summarizes it`)
    assert.ok(r.explore?.length > 20, `${r.id} has an explore line`)
  }
  assert.ok(!html.includes('undefined') && !html.includes('NaN'))
})

test('the error pages say what happened and offer the way out', () => {
  const missing = harness.renderNotFound('#r9')
  assert.ok(missing.includes('Page not found') && missing.includes('<code>#r9</code>'), 'names the bad link')
  assert.ok(missing.includes('href="#home" class="button button-primary"'), 'links home')
  for (const r of harness.REPORTS) assert.ok(missing.includes(`href="#${r.id}"`), `links ${r.id}`)
  assert.ok(missing.includes('role="alert"'))

  const crashed = harness.renderCrashed(new Error('boom in R2'))
  assert.ok(crashed.includes('Something went wrong') && crashed.includes('This page hit an error'))
  assert.ok(crashed.includes('Reload the page') && crashed.includes('href="#home"'), 'reload and home actions')
  assert.ok(crashed.includes('<summary>Technical details</summary>') && crashed.includes('boom in R2'), 'details folded away')

  const failed = harness.renderStatus({ error: "Couldn't reach the report service.", onRetry: () => {} })
  assert.ok(failed.includes("This report didn&#x27;t load.") && failed.includes('reach the report service'))
  assert.ok(failed.includes('>Try again</button>'), 'a retry button when a retry is possible')
  assert.ok(!failed.includes('8080'), 'no developer-only port in a message visitors see')
  assert.ok(!harness.renderStatus({ error: 'x' }).includes('Try again'), 'no button without a retry')
  assert.ok(harness.renderStatus({ empty: true, loading: false }).includes('No deliveries match these filters'))
})

test('the dark theme redefines every colour token, both ways it can switch on', () => {
  const css = readFileSync(path.join(here, '..', 'src', 'styles.css'), 'utf8')
  const block = (re) => css.match(re)?.[1] ?? ''
  const colourTokens = (body) =>
    [...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)]
      .filter(([, , value]) => /#[0-9a-f]{3,8}\b|rgba?\(/i.test(value))
      .map(([, name]) => name)
      .sort()
  const light = colourTokens(block(/:root \{([\s\S]*?)\n\}/))
  const system = colourTokens(block(/:root:not\(\[data-theme='light'\]\) \{([\s\S]*?)\n {2}\}/))
  const pinned = colourTokens(block(/:root\[data-theme='dark'\] \{([\s\S]*?)\n\}/))
  assert.ok(light.length > 10, `${light.length} light colour tokens`)
  assert.deepEqual(system, light, 'the system-setting dark block')
  assert.deepEqual(pinned, light, 'the data-theme="dark" block')
})

test('the theme switch follows the system until a choice pins it', () => {
  const root = { dataset: {} }
  const system = (dark) => () => ({ matches: dark })
  assert.equal(currentTheme(root, system(true)), 'dark', 'no choice yet: the system setting')
  assert.equal(currentTheme(root, system(false)), 'light')

  const saved = {}
  const storage = { setItem: (k, v) => (saved[k] = v) }
  applyTheme(otherTheme('dark'), root, storage)
  assert.equal(root.dataset.theme, 'light')
  assert.equal(saved[THEME_KEY], 'light', 'the choice is remembered')
  assert.equal(currentTheme(root, system(true)), 'light', 'a pinned choice beats the system setting')

  const blocked = { setItem: () => { throw new Error('storage disabled') } }
  assert.doesNotThrow(() => applyTheme('dark', root, blocked), 'blocked storage still switches')
  assert.equal(root.dataset.theme, 'dark')

  const html = readFileSync(path.join(here, '..', 'index.html'), 'utf8')
  assert.ok(html.includes(`localStorage.getItem('${THEME_KEY}')`), 'index.html restores the same key before paint')
})

test('light-theme muted text meets WCAG AA on every light background', () => {
  const css = readFileSync(path.join(here, '..', 'src', 'styles.css'), 'utf8')
  const light = css.match(/:root \{([\s\S]*?)\n\}/)[1]
  const token = (name) => light.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, 'i'))[1]
  const channel = (hex, i) => {
    const v = parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  const luminance = (hex) => 0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 1) + 0.0722 * channel(hex, 2)
  const contrast = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
    return (hi + 0.05) / (lo + 0.05)
  }
  for (const bg of ['--surface', '--surface-2', '--paper', '--route-tint', '--signal-tint']) {
    const ratio = contrast(token('--ink-3'), token(bg))
    assert.ok(ratio >= 4.5, `--ink-3 on ${bg} is ${ratio.toFixed(2)}:1`)
  }
})

test('a report that renames its state literal fails the harness instead of passing', async () => {
  const broken = { ...PATCHES, FleetWorkloadReport: [...PATCHES.FleetWorkloadReport, ["useState('nope')", 'x']] }
  await assert.rejects(buildHarness(broken), /the state patch matched nothing/)
})
