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

// ---------- R3 Customer Value Distribution ----------

// Warehouse totals for the whole slice, used to size the sample (1M orders,
// ~11M units, ~100k customers, ₱54.8B list-price value).
const TOTAL_ORDERS = 1000000
const TOTAL_VALUE = 54847773793
const TOTAL_CUSTOMERS = 99996
// Decile 1 (the top 10% of customers by value) holds this share of the slice.
const DECILE_SHARES = [17.5, 14.1, 12.5, 11.2, 10.2, 9.2, 8.2, 7.2, 6.0, 3.9]
const FEMALE_SHARE = 0.503

const COUNTRIES = ['Philippines', 'Indonesia', 'Malaysia', 'Thailand', 'Vietnam', 'Singapore', 'Japan',
  'South Korea', 'India', 'Australia', 'New Zealand', 'United States', 'Canada', 'Mexico', 'Brazil',
  'Argentina', 'Chile', 'Colombia', 'Peru', 'United Kingdom', 'Germany', 'France', 'Spain', 'Italy',
  'Netherlands', 'Poland', 'Sweden', 'Turkey', 'Egypt', 'Nigeria', 'Kenya', 'South Africa',
  'Saudi Arabia', 'United Arab Emirates', 'Pakistan', 'Bangladesh', 'Sudan', 'Dominican Republic',
  'North Macedonia', 'Scotland']

// The mock keeps 40 countries but sizes them as though the warehouse's 240 were
// all present, so one country holds a warehouse-like share of the total (~0.4%).
const COUNTRY_SCALE = 6
function countryWeight(name) {
  const r = seeded(`r3country|${name}`)
  return 1 + r() * 0.8
}
const COUNTRY_WEIGHT_SUM = COUNTRIES.reduce((sum, c) => sum + countryWeight(c), 0)

const CITY_PREFIX = ['Ortiz', 'Eleanor', 'Kuphal', 'Manila', 'Cebu', 'Davao', 'Jakarta', 'Bangkok', 'Hanoi',
  'Singapore', 'Tokyo', 'Seoul', 'Sydney', 'Mumbai', 'Austin', 'Khartoum', 'Santo', 'Bello', 'North', 'Port']
const CITY_SUFFIX = ['furt', 'astead', 'ton', 'ville', 'burg', 'stad', 'field', 'mouth', 'borough', 'city']

function citiesFor(country) {
  const r = seeded(`cities|${country}`)
  return Array.from(
    { length: 6 },
    () => `${CITY_PREFIX[Math.floor(r() * CITY_PREFIX.length)]}${CITY_SUFFIX[Math.floor(r() * CITY_SUFFIX.length)]}`,
  )
}

// DIM_CUSTOMER usernames are opaque 10-character mixed-case strings.
const LETTERS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
const username = (r) => Array.from({ length: 10 }, () => LETTERS[Math.floor(r() * LETTERS.length)]).join('')

function r3Deciles(p) {
  const r = seeded(`r3dec|${p.country}|${p.gender}|${p.year}|${p.quarter}`)
  const frac = daysIn(p) / 365
  const genderFrac = p.gender ? 0.5 : 1
  const sliceValue = TOTAL_VALUE * frac * genderFrac
  const sliceCustomers = Math.round(TOTAL_CUSTOMERS * frac * genderFrac)
  const weights = DECILE_SHARES.map((w) => w * (0.97 + r() * 0.06))
  const weightSum = weights.reduce((a, b) => a + b, 0)
  const smallest = Math.floor(sliceCustomers / 10)

  let running = 0
  return weights.map((w, i) => {
    const shape = w / weightSum
    const customers = smallest + (i < sliceCustomers % 10 ? 1 : 0)
    const value = sliceValue * shape
    const avg = value / customers
    running += 100 * shape
    return {
      decile: i + 1,
      customers,
      value: round2(value),
      value_share_pct: round1(100 * shape),
      cumulative_share_pct: round1(Math.min(100, running)),
      avg_value_per_customer: round2(avg),
      min_customer_value: round2(avg * (0.45 + i * 0.045)),
      max_customer_value: round2(avg * (3.1 - i * 0.22)),
    }
  })
}

function r3Geography(p) {
  const level = p.level === 'city' ? 'city' : 'country'
  // city.sql always runs inside one country; outside one there is nothing to show.
  if (level === 'city' && !p.country) return []

  const topN = Number(p.top_n) || 20
  const frac = daysIn(p) / 365
  const genderFrac = p.gender ? 0.5 : 1
  const r = seeded(`r3geo|${p.level}|${p.country}|${p.gender}|${p.year}|${p.quarter}`)

  let customers = TOTAL_CUSTOMERS * frac * genderFrac
  let orders = TOTAL_ORDERS * frac * genderFrac
  let value = TOTAL_VALUE * frac * genderFrac
  let names = COUNTRIES
  // The 40 mock countries cover a sixth of the total; one country's cities cover all of it.
  let weights
  let pool
  if (level === 'city') {
    const share = countryWeight(p.country) / (COUNTRY_WEIGHT_SUM * COUNTRY_SCALE)
    customers *= share
    orders *= share
    value *= share
    names = citiesFor(p.country)
    const citySeed = seeded(`r3cities|${p.country}`)
    weights = names.map(() => 1 + citySeed() * 0.8)
    pool = weights.reduce((a, b) => a + b, 0)
  } else {
    weights = names.map(countryWeight)
    pool = COUNTRY_WEIGHT_SUM * COUNTRY_SCALE
  }

  const locations = names
    .map((name, i) => ({
      location: name,
      customers: customers * (weights[i] / pool),
      orders: orders * (weights[i] / pool),
      value: value * (weights[i] / pool),
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, topN)

  const ranks = rank(locations, (x) => x.value)
  const perCustomer = (v, c) => (c ? round2(v / c) : null)
  const rows = []
  for (const loc of locations) {
    const share = FEMALE_SHARE + (r() - 0.5) * 0.04
    const c = Math.round(loc.customers)
    const o = Math.round(loc.orders)
    const v = round2(loc.value)
    const femaleCustomers = Math.round(c * share)
    const femaleOrders = Math.round(o * share)
    const femaleValue = round2(v * share)
    const valueRank = ranks.get(loc)
    rows.push(
      { location: loc.location, gender: 'All', customers: c, orders: o, value: v, value_per_customer: perCustomer(v, c), value_rank: valueRank, grouping_level: 1 },
      { location: loc.location, gender: 'F', customers: femaleCustomers, orders: femaleOrders, value: femaleValue, value_per_customer: perCustomer(femaleValue, femaleCustomers), value_rank: valueRank, grouping_level: 0 },
      { location: loc.location, gender: 'M', customers: c - femaleCustomers, orders: o - femaleOrders, value: round2(v - femaleValue), value_per_customer: perCustomer(v - femaleValue, c - femaleCustomers), value_rank: valueRank, grouping_level: 0 },
    )
  }

  // The subtotals cover the whole selection, not just the rows top_n left on screen.
  const totalCustomers = Math.round(customers)
  const totalOrders = Math.round(orders)
  const totalValue = round2(value)
  rows.push({
    location: 'All locations', gender: 'All', customers: totalCustomers, orders: totalOrders, value: totalValue,
    value_per_customer: perCustomer(totalValue, totalCustomers), value_rank: null, grouping_level: 3,
  })
  for (const gender of ['F', 'M']) {
    const part = gender === 'F' ? FEMALE_SHARE : 1 - FEMALE_SHARE
    const c = Math.round(totalCustomers * part)
    const v = round2(totalValue * part)
    rows.push({
      location: 'All locations', gender, customers: c, orders: Math.round(totalOrders * part), value: v,
      value_per_customer: perCustomer(v, c), value_rank: null, grouping_level: 2,
    })
  }
  return rows
}

function r3Customer(p) {
  const topN = Number(p.top_n) || 20
  const r = seeded(`r3cust|${p.country}|${p.city}|${p.gender}|${p.decile}|${p.year}|${p.quarter}`)
  // Draw from the decile ranges, so the top table and the decile chart describe
  // the same slice instead of two independent sets of numbers.
  const bands = r3Deciles(p)
  const pool = Array.from({ length: 300 }, () => {
    const band = bands[Math.min(9, Math.floor(r() * 10))]
    const country = p.country || COUNTRIES[Math.floor(r() * COUNTRIES.length)]
    return {
      customer: username(r),
      gender: p.gender || (r() < 0.5 ? 'F' : 'M'),
      country,
      city: p.city || citiesFor(country)[Math.floor(r() * 6)],
      value: band.min_customer_value + r() * Math.max(0, band.max_customer_value - band.min_customer_value),
    }
  }).sort((a, b) => b.value - a.value)

  const ranks = rank(pool, (x) => x.value)
  const rows = pool.map((x, i) => {
    const orders = Math.max(1, Math.round(x.value / (58000 + r() * 26000)))
    const value = round2(x.value)
    return {
      value_rank: ranks.get(x),
      customer: x.customer,
      country: x.country,
      city: x.city,
      gender: x.gender,
      orders,
      units: Math.round(orders * UNITS_PER_ORDER),
      value,
      avg_order_value: round2(value / orders),
      // NTILE(10) over the pool, and PERCENT_RANK over value ascending, so 100
      // means "worth at least as much as everyone else in the slice".
      decile: Math.min(10, Math.floor((i / pool.length) * 10) + 1),
      value_percentile: pool.length > 1 ? round1((100 * (pool.length - 1 - i)) / (pool.length - 1)) : 100,
    }
  })

  const chosen = p.decile ? rows.filter((x) => x.decile === Number(p.decile)) : rows
  return chosen.slice(0, topN)
}

// ---------- dispatch ----------

const LEVELS = {
  'r1/category': r1Category,
  'r1/product': r1Product,
  'r2/cube': r2Cube,
  'r2/pivot': r2Pivot,
  'r2/rider': r2Rider,
  'r3/deciles': r3Deciles,
  'r3/geography': r3Geography,
  'r3/customer': r3Customer,
}

export function mockReport(report, level, params) {
  const build = LEVELS[`${report}/${level}`]
  if (!build) throw new Error(`No sample data for ${report}/${level} yet.`)
  return build(params)
}
