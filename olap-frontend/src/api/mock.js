// Sample data for building the dashboard before the Go API is ready.
//
// Each function returns rows with exactly the columns, ordering and total
// rows that the matching SQL file returns, so switching to VITE_API_MODE=live
// needs no UI changes. The numbers are invented but sized like the real
// warehouse (1M orders, ~11M units, 100 riders, 24 Sep 2024 to 23 Sep 2025)
// and react to every filter. They are NOT warehouse results.

// ---------- shared helpers ----------

// Seeded random numbers, so the same filters always show the same sample.
function seeded(text) {
  let h = 1779033703 ^ text.length
  for (let i = 0; i < text.length; i++) {
    h = Math.imul(h ^ text.charCodeAt(i), 3432918353)
    h = (h << 13) | (h >>> 19)
  }
  let a = h >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const round1 = (x) => Math.round(x * 10) / 10
const round2 = (x) => Math.round(x * 100) / 100
const share = (part, whole) => (whole ? round1((100 * part) / whole) : null)
const byText = (a, b) => String(a).localeCompare(String(b))

// The 365 delivery dates in the warehouse.
const FIRST_DAY = Date.UTC(2024, 8, 24)
const DAYS = Array.from({ length: 365 }, (_, i) => {
  const d = new Date(FIRST_DAY + i * 86400000)
  const month = d.getUTCMonth() + 1
  return { year: d.getUTCFullYear(), month, quarter: Math.ceil(month / 3) }
})

function daysIn(p) {
  return DAYS.filter(
    (d) =>
      (!p.year || d.year === Number(p.year)) &&
      (!p.quarter || d.quarter === Number(p.quarter)) &&
      (!p.month || d.month === Number(p.month)),
  ).length
}

// RANK(): ties share a rank, the next rank skips.
function rank(items, value, descending = true) {
  const sorted = [...items].sort((a, b) => (descending ? value(b) - value(a) : value(a) - value(b)))
  const ranks = new Map()
  sorted.forEach((item, i) => {
    const prev = sorted[i - 1]
    ranks.set(item, prev && value(prev) === value(item) ? ranks.get(prev) : i + 1)
  })
  return ranks
}

// ---------- reference data ----------

const TOTAL_UNITS = 10999917
const UNITS_PER_ORDER = 11
const ORDERS_PER_RIDER_DAY = 27.4

// category -> number of products (after the ETL merged spelling variants)
const CATEGORIES = [
  ['Toys', 2172], ['Bags', 1445], ['Makeup', 1404], ['Gadgets', 1396], ['Clothes', 745],
  ["Men's Apparel", 721], ['Electronics', 718], ['Appliances', 712], ['Laptops', 687],
]
const AVG_PRICE = {
  Toys: 4930, Bags: 5060, Makeup: 4880, Gadgets: 5110, Clothes: 4950,
  "Men's Apparel": 5020, Electronics: 4990, Appliances: 5070, Laptops: 4860,
}

const VEHICLE_RIDERS = { Motorcycle: 42, Bicycle: 29, Car: 15, Trike: 14 }
const SIZE_SHARE = { Light: 0.56, Heavy: 0.44 }
const COURIERS = ['FEDEZ', 'JNT', 'LBCD']
const AGE_BANDS = ['18-29', '30-39', '40-49', '50-60']

const FIRST_NAMES = ['Andres', 'Bea', 'Carlo', 'Dana', 'Enzo', 'Faye', 'Gabriel', 'Hannah', 'Ivan', 'Jasmine',
  'Kevin', 'Lia', 'Miguel', 'Nina', 'Oscar', 'Paula', 'Rafael', 'Sofia', 'Tomas', 'Vina']
const LAST_NAMES = ['Reyes', 'Santos', 'Cruz', 'Bautista', 'Garcia', 'Mendoza', 'Torres', 'Flores', 'Ramos',
  'Aquino', 'Navarro', 'Castillo', 'Villanueva', 'Marquez', 'Domingo', 'Salazar']

const RIDERS = (() => {
  const r = seeded('riders')
  const list = []
  for (const [vehicle, count] of Object.entries(VEHICLE_RIDERS)) {
    for (let i = 0; i < count; i++) {
      list.push({
        key: list.length + 1,
        name: `${FIRST_NAMES[Math.floor(r() * FIRST_NAMES.length)]} ${LAST_NAMES[Math.floor(r() * LAST_NAMES.length)]}`,
        vehicle,
        courier: COURIERS[Math.floor(r() * COURIERS.length)],
        ageBand: AGE_BANDS[Math.floor(r() * AGE_BANDS.length)],
        pace: 0.975 + r() * 0.05,
      })
    }
  }
  return list
})()

const ADJECTIVES = ['Incredible', 'Tasty', 'Sleek', 'Rustic', 'Ergonomic', 'Handcrafted', 'Practical', 'Gorgeous',
  'Refined', 'Licensed', 'Generic', 'Fantastic', 'Intelligent', 'Small', 'Awesome', 'Modern']
const MATERIALS = ['Metal', 'Wooden', 'Cotton', 'Granite', 'Plastic', 'Steel', 'Rubber', 'Bronze', 'Frozen', 'Soft', 'Concrete']
const NOUNS = ['Shirt', 'Fish', 'Chair', 'Ball', 'Keyboard', 'Shoes', 'Gloves', 'Lamp', 'Bike', 'Towels', 'Hat',
  'Table', 'Pizza', 'Bacon', 'Computer', 'Mouse', 'Soap', 'Cheese', 'Car', 'Sausages']

// ---------- R1 Product & Category Value ----------

function categoryTotals(p) {
  const frac = daysIn(p) / 365
  const vehicleFrac = p.vehicle ? VEHICLE_RIDERS[p.vehicle] / 100 : 1
  const sizeFrac = p.size_group ? SIZE_SHARE[p.size_group] : 1
  const r = seeded(`r1|${p.year}|${p.quarter}|${p.month}|${p.vehicle}|${p.size_group}`)
  return CATEGORIES.map(([category, products]) => {
    const units = Math.round(TOTAL_UNITS * frac * vehicleFrac * sizeFrac * (products / 10000) * (0.97 + r() * 0.06))
    return { category, products, units, value: round2(units * AVG_PRICE[category] * (0.98 + r() * 0.04)) }
  }).filter((c) => c.units > 0)
}

function r1Category(p) {
  const cats = categoryTotals(p)
  const totalUnits = cats.reduce((s, c) => s + c.units, 0)
  const totalValue = round2(cats.reduce((s, c) => s + c.value, 0))
  const ranks = rank(cats, (c) => c.value)
  const rows = [...cats]
    .sort((a, b) => b.value - a.value)
    .map((c) => ({
      category: c.category,
      units: c.units,
      value: c.value,
      value_share_pct: share(c.value, totalValue),
      value_rank: ranks.get(c),
      is_total: false,
    }))
  rows.push({
    category: 'All categories',
    units: cats.length ? totalUnits : null,
    value: cats.length ? totalValue : null,
    value_share_pct: cats.length ? 100 : null,
    value_rank: null,
    is_total: true,
  })
  return rows
}

function r1Product(p) {
  const topN = Number(p.top_n) || 10
  const cats = categoryTotals(p).filter((c) => !p.category || c.category === p.category)
  const rows = []
  for (const c of [...cats].sort((a, b) => byText(a.category, b.category))) {
    const r = seeded(`r1p|${c.category}|${p.year}|${p.quarter}|${p.month}|${p.vehicle}|${p.size_group}`)
    const avg = c.value / c.products
    // Leaders sit 1.6x to 2.4x above the category's average product.
    const products = Array.from({ length: Math.min(topN, c.products) }, (_, i) => {
      const price = 400 + Math.floor(r() * 9500)
      const target = avg * (2.4 - (0.8 * i) / Math.max(topN - 1, 1)) * (0.97 + r() * 0.06)
      const units = Math.max(1, Math.round(target / price))
      return {
        product: `${ADJECTIVES[Math.floor(r() * ADJECTIVES.length)]} ${MATERIALS[Math.floor(r() * MATERIALS.length)]} ${NOUNS[Math.floor(r() * NOUNS.length)]}`,
        units,
        value: round2(units * price),
      }
    })
    const ranks = rank(products, (x) => x.value)
    products
      .sort((a, b) => b.value - a.value)
      .forEach((x) =>
        rows.push({
          category: c.category,
          product: x.product,
          units: x.units,
          value: x.value,
          share_of_category_pct: share(x.value, c.value),
          rank_in_category: ranks.get(x),
          is_subtotal: false,
        }),
      )
    rows.push({
      category: c.category,
      product: 'All products',
      units: c.units,
      value: c.value,
      share_of_category_pct: 100,
      rank_in_category: null,
      is_subtotal: true,
    })
  }
  return rows
}

// ---------- R2 Fleet, Courier & Rider Workload ----------

function ridersMatching(p) {
  return RIDERS.filter(
    (rd) =>
      (!p.courier || rd.courier === p.courier) &&
      (!p.vehicle || rd.vehicle === p.vehicle) &&
      (!p.age_band || rd.ageBand === p.age_band),
  )
}

function ordersFor(rider, p, days, useSize) {
  const r = seeded(`orders|${rider.key}|${p.year}|${p.quarter}|${p.month}`)
  const sizeFrac = useSize && p.size_group ? SIZE_SHARE[p.size_group] : 1
  return Math.round(ORDERS_PER_RIDER_DAY * days * rider.pace * sizeFrac * (0.99 + r() * 0.02))
}

// One entry per rider with at least one order, like the order fact after filtering.
function deliveries(p) {
  const days = daysIn(p)
  return ridersMatching(p)
    .map((rd) => {
      const orders = days ? ordersFor(rd, p, days, true) : 0
      return { rider: rd, orders, units: Math.round(orders * UNITS_PER_ORDER) }
    })
    .filter((x) => x.orders > 0)
}

function summarize(list) {
  return {
    orders: list.reduce((s, x) => s + x.orders, 0),
    units: list.length ? list.reduce((s, x) => s + x.units, 0) : null,
    riders: list.length,
  }
}

function r2Cube(p) {
  const data = deliveries(p)
  const groups = []
  const add = (courier, vehicle, level, list) => {
    if (!list.length && level !== 3) return
    groups.push({ courier, vehicle, ...summarize(list), grouping_level: level })
  }
  const couriers = [...new Set(data.map((x) => x.rider.courier))]
  const vehicles = [...new Set(data.map((x) => x.rider.vehicle))]
  for (const c of couriers) {
    for (const v of vehicles) add(c, v, 0, data.filter((x) => x.rider.courier === c && x.rider.vehicle === v))
  }
  for (const c of couriers) add(c, 'All vehicles', 1, data.filter((x) => x.rider.courier === c))
  for (const v of vehicles) add('All couriers', v, 2, data.filter((x) => x.rider.vehicle === v))
  add('All couriers', 'All vehicles', 3, data)

  const totalOrders = groups.find((g) => g.grouping_level === 3).orders
  return groups
    .map((g) => ({
      courier: g.courier,
      vehicle: g.vehicle,
      orders: g.orders,
      units: g.units,
      riders: g.riders,
      orders_per_rider: g.riders ? Math.round(g.orders / g.riders) : null,
      order_share_pct: share(g.orders, totalOrders),
      grouping_level: g.grouping_level,
    }))
    .sort((a, b) => a.grouping_level - b.grouping_level || byText(a.courier, b.courier) || byText(a.vehicle, b.vehicle))
}

function r2Pivot(p) {
  const data = deliveries(p)
  const perRider = p.measure === 'per_rider'
  const cell = (list) => {
    const s = summarize(list)
    if (perRider) return s.riders ? Math.round(s.orders / s.riders) : null
    return s.orders
  }
  const row = (courier, list, isTotal) => ({
    courier,
    motorcycle: cell(list.filter((x) => x.rider.vehicle === 'Motorcycle')),
    bicycle: cell(list.filter((x) => x.rider.vehicle === 'Bicycle')),
    car: cell(list.filter((x) => x.rider.vehicle === 'Car')),
    trike: cell(list.filter((x) => x.rider.vehicle === 'Trike')),
    total: cell(list),
    riders: list.length,
    is_total: isTotal,
  })
  const couriers = [...new Set(data.map((x) => x.rider.courier))].sort(byText)
  return [...couriers.map((c) => row(c, data.filter((x) => x.rider.courier === c), false)), row('All couriers', data, true)]
}

function r2Rider(p) {
  const days = daysIn(p)
  const rows = ridersMatching(p).map((rd) => {
    const r = seeded(`rider|${rd.key}|${p.year}|${p.quarter}|${p.month}`)
    const orders = days ? ordersFor(rd, p, days, false) : 0
    return {
      rider: rd.name,
      courier: rd.courier,
      vehicle: rd.vehicle,
      age_band: rd.ageBand,
      orders,
      units: Math.round(orders * UNITS_PER_ORDER * (0.98 + r() * 0.04)),
      active_days: days,
      calendar_days: days,
      peak_day_orders: days ? Math.round(ORDERS_PER_RIDER_DAY * rd.pace * (1.45 + r() * 0.25)) : null,
    }
  })
  const ranks = rank(rows, (x) => x.orders)
  const ascending = rank(rows, (x) => x.orders, false)
  const ranked = rows.map((x) => ({
    workload_rank: ranks.get(x),
    rider: x.rider,
    courier: x.courier,
    vehicle: x.vehicle,
    age_band: x.age_band,
    orders: x.orders,
    units: x.units,
    active_days: x.active_days,
    calendar_days: x.calendar_days,
    utilization_pct: share(x.active_days, x.calendar_days),
    avg_orders_per_active_day: x.active_days ? round1(x.orders / x.active_days) : null,
    peak_day_orders: x.peak_day_orders,
    // PERCENT_RANK() = (rank - 1) / (rows - 1)
    workload_percentile: rows.length > 1 ? round1((100 * (ascending.get(x) - 1)) / (rows.length - 1)) : 0,
  }))
  const least = p.sort === 'least'
  ranked.sort((a, b) => (least ? a.orders - b.orders : b.orders - a.orders) || byText(a.rider, b.rider))
  return ranked.slice(0, Number(p.top_n) || 20)
}

// ---------- dispatch ----------

const LEVELS = {
  'r1/category': r1Category,
  'r1/product': r1Product,
  'r2/cube': r2Cube,
  'r2/pivot': r2Pivot,
  'r2/rider': r2Rider,
}

export function mockReport(report, level, params) {
  const build = LEVELS[`${report}/${level}`]
  if (!build) throw new Error(`No sample data for ${report}/${level} yet.`)
  return build(params)
}
