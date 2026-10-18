"""Shared helpers for the functional tests.

Nothing here imports code from the project under test. The expected values
come from two places that do not share code with the report SQL or the API:

  * source_db, normalised the way the ETL is specified to (two date formats,
    14 category spellings, vehicle and gender spellings), and
  * plain Python re-implementations of every report formula, including the
    rounding rules.

All database access is read-only (default_transaction_read_only is forced on
for every psql session), so the suite cannot change either database.
"""
import calendar
import datetime
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_left, bisect_right
from collections import defaultdict, namedtuple
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from functools import lru_cache
from math import floor

API_ROOT = os.environ.get("API", "http://localhost:8080").rstrip("/")
DW_CONTAINER = os.environ.get("DW_CONTAINER", "stadvdb-mco1-dw-db")
SRC_CONTAINER = os.environ.get("SRC_CONTAINER", "stadvdb-mco1-source-db")
REPORTS = "/api/reports"

# Deliberately wrong reference data, to prove the tests can fail
# (see README.md, "Negative control").
NEGATIVE_CONTROL = os.environ.get("DWTEST_NEGATIVE_CONTROL") == "1"

VEHICLES = ("Bicycle", "Motorcycle", "Car", "Trike")
CATEGORIES = ("Appliances", "Bags", "Clothes", "Electronics", "Gadgets",
              "Laptops", "Makeup", "Men's Apparel", "Toys")
COURIERS = ("FEDEZ", "JNT", "LBCD")
SIZE_GROUPS = ("Light", "Heavy")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")

# The columns each level must return, in order (olap-backend/internal/reports/catalog.go).
LEVEL_COLUMNS = {
    ("r1", "category"): ["category", "units", "value", "value_share_pct", "value_rank", "is_total"],
    ("r1", "product"): ["category", "product", "units", "value", "share_of_category_pct",
                        "rank_in_category", "is_subtotal"],
    ("r2", "courier_vehicle_cube"): ["courier", "vehicle", "orders", "units", "riders",
                                     "orders_per_rider", "order_share_pct", "grouping_level"],
    ("r2", "courier_vehicle_pivot"): ["courier", "motorcycle", "bicycle", "car", "trike",
                                      "total", "riders", "is_total"],
    ("r2", "rider"): ["workload_rank", "rider", "courier", "vehicle", "age_band", "orders",
                      "units", "active_days", "calendar_days", "utilization_pct",
                      "avg_orders_per_active_day", "peak_day_orders", "workload_percentile"],
    ("r3", "deciles"): ["decile", "customers", "value", "value_share_pct", "cumulative_share_pct",
                        "avg_value_per_customer", "min_customer_value", "max_customer_value"],
    ("r3", "geography"): ["location", "gender", "customers", "orders", "value",
                          "value_per_customer", "value_rank", "grouping_level"],
    ("r3", "customer"): ["value_rank", "customer", "country", "city", "gender", "orders",
                         "units", "value", "avg_order_value", "decile", "value_percentile"],
    ("r4", "rollup"): ["hierarchy_level", "year", "quarter", "month", "month_name", "days",
                       "orders", "units", "orders_per_day"],
    ("r4", "trend"): ["period_label", "period_start", "days", "orders", "units",
                      "orders_per_day", "change_vs_previous_pct", "moving_avg_orders_per_day"],
    ("r4", "weekday_pivot"): ["month_label", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
                              "all_days", "is_total"],
    ("r4", "busiest_days"): ["demand_rank", "date", "day_name", "is_weekend", "is_payday",
                             "orders", "units", "active_riders", "orders_per_active_rider",
                             "vs_average_pct"],
}


# --------------------------------------------------------------------- access

def psql(container, db, sql, timeout=900):
    """Run read-only SQL and return the rows as lists of strings (NULL = '')."""
    cmd = ["docker", "exec", "-i", "-e", "PGOPTIONS=-c default_transaction_read_only=on",
           container, "psql", "-X", "-At", "-F", "\t", "-U", "postgres", "-d", db,
           "-v", "ON_ERROR_STOP=1"]
    done = subprocess.run(cmd, input=sql, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError("psql failed on %s/%s: %s" % (container, db, done.stderr.strip()[:600]))
    return [line.split("\t") for line in done.stdout.splitlines() if line != ""]


def dw(sql):
    return psql(DW_CONTAINER, "dw_db", sql)


def src(sql):
    return psql(SRC_CONTAINER, "source_db", sql)


def dw_scalar(sql):
    return dw(sql)[0][0]


def src_scalar(sql):
    return src(sql)[0][0]


def api_get(path, **filters):
    """GET and return (status, parsed JSON). 4xx and 5xx do not raise."""
    query = urllib.parse.urlencode({k: str(v) for k, v in filters.items() if v not in (None, "")})
    url = API_ROOT + path + ("?" + query if query else "")
    try:
        with urllib.request.urlopen(url, timeout=180) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read()
    try:
        body = json.loads(raw)
    except ValueError:
        body = {"_raw": raw[:200].decode("utf-8", "replace")}
    return status, body


_report_cache = {}


def report(report_id, level, /, **filters):
    """200-only report call (cached: the data does not change during a run)."""
    key = (report_id, level, tuple(sorted((k, str(v)) for k, v in filters.items() if v != "")))
    if key not in _report_cache:
        status, body = api_get("%s/%s/%s" % (REPORTS, report_id, level), **filters)
        if status != 200:
            raise AssertionError("GET %s/%s/%s %r -> HTTP %s: %s"
                                 % (REPORTS, report_id, level, filters, status, ascii(body)[:300]))
        _report_cache[key] = body
    return _report_cache[key]


# ------------------------------------------------------------------ preflight

class PreflightError(AssertionError):
    pass


@lru_cache(maxsize=None)
def preflight():
    """Fail fast, with a clear message, when the environment is not ready."""
    problems = []
    states = {}
    for name in (DW_CONTAINER, SRC_CONTAINER):
        try:
            out = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", name],
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
            states[name] = out.stdout.strip() if out.returncode == 0 else "missing"
        except (OSError, subprocess.SubprocessError) as err:
            states[name] = "docker unavailable (%s)" % err
        if states[name] != "running":
            problems.append("container %s is %s (start it with: docker compose up -d)"
                            % (name, states[name]))
    health = None
    try:
        status, health = api_get("/api/health")
        if status != 200 or health != {"database": "ok", "status": "ok"}:
            problems.append("GET /api/health -> %s %s" % (status, health))
    except (OSError, urllib.error.URLError) as err:
        problems.append("API not reachable at %s (%s). Start it with: "
                        "docker compose --profile app up -d --no-deps api" % (API_ROOT, err))
    if not problems:
        for label, run in (("dw_db", dw), ("source_db", src)):
            try:
                if run("SELECT 1")[0][0] != "1":
                    problems.append("%s did not answer SELECT 1" % label)
            except (RuntimeError, OSError, subprocess.SubprocessError) as err:
                problems.append("%s unreachable: %s" % (label, err))
    if problems:
        raise PreflightError("PREFLIGHT FAILED:\n  - " + "\n  - ".join(problems))
    return {"containers": states, "health": health}


# ------------------------------------------------------------- number helpers

def rnd(value, places):
    """Postgres numeric round(): half away from zero, exact on fractions."""
    scaled = Fraction(value) * (10 ** places)
    n = floor(abs(scaled) + Fraction(1, 2))
    return Decimal(-n if scaled < 0 else n).scaleb(-places)


def money(cents):
    return Decimal(cents).scaleb(-2)


def percent_rank_pct(rank_asc, n):
    """round((100 * PERCENT_RANK())::numeric, 1): the window function is float8."""
    fraction = 0.0 if n <= 1 else (rank_asc - 1) / (n - 1)
    # float8 -> numeric keeps 15 significant digits.
    return Decimal(format(100 * fraction, ".15g")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def ntile_bucket(position, n, tiles=10):
    """NTILE(tiles) bucket (1-based) of a 0-based row position among n rows."""
    base, extra = divmod(n, tiles)
    larger = extra * (base + 1)
    if position < larger:
        return position // (base + 1) + 1
    return extra + (position - larger) // base + 1


def same(api_value, ref_value):
    if isinstance(ref_value, (set, frozenset)):
        return api_value in ref_value
    if isinstance(ref_value, Decimal):
        ref_value = float(ref_value)
    if isinstance(api_value, bool) or isinstance(ref_value, bool):
        return api_value is ref_value
    return api_value == ref_value


def diff_rows(got, want, columns):
    """First difference between API rows and reference rows, or None."""
    if len(got) != len(want):
        return "row count: api=%d reference=%d" % (len(got), len(want))
    for i, (g, w) in enumerate(zip(got, want)):
        if set(g) != set(columns):
            return "row %d has keys %s, expected %s" % (i, sorted(g), sorted(columns))
        for col in columns:
            if not same(g[col], w[col]):
                return "row %d column %s: api=%r reference=%r\n  api: %s\n  ref: %s" % (
                    i, col, g[col], w[col], ascii(g), ascii(w))
    return None


def diff_tie_aware(got, want_all, columns, order_col, id_col, limit):
    """Compare a LIMITed, ranked list where equal values may come in any order.

    The sort-key sequence must match the reference, and each returned row must
    equal the reference row with the same id (so rank and decile match too).
    """
    expected = min(limit, len(want_all))
    if len(got) != expected:
        return "row count: api=%d reference=%d" % (len(got), expected)
    by_id = {w[id_col]: w for w in want_all}
    seen = set()
    for i, g in enumerate(got):
        if set(g) != set(columns):
            return "row %d has keys %s, expected %s" % (i, sorted(g), sorted(columns))
        if not same(g[order_col], want_all[i][order_col]):
            return "row %d %s: api=%r reference=%r" % (i, order_col, g[order_col], want_all[i][order_col])
        if g[id_col] in seen or g[id_col] not in by_id:
            return "row %d id %r is duplicated or unknown" % (i, g[id_col])
        seen.add(g[id_col])
        w = by_id[g[id_col]]
        for col in columns:
            if not same(g[col], w[col]):
                return "row %d (%s) column %s: api=%r reference=%r\n  api: %s\n  ref: %s" % (
                    i, g[id_col], col, g[col], w[col], ascii(g), ascii(w))
    return None


# ------------------------------------------------------------------- calendar

DateInfo = namedtuple("DateInfo", "year quarter month day weekend payday week day_name month_name")


@lru_cache(maxsize=None)
def dateinfo(d):
    """Calendar attributes from the date alone: no warehouse involved."""
    last_day = calendar.monthrange(d.year, d.month)[1]
    return DateInfo(
        year=d.year, quarter=(d.month - 1) // 3 + 1, month=d.month, day=d.day,
        weekend=d.isoweekday() in (6, 7), payday=d.day in (15, last_day),
        week=(d.timetuple().tm_yday - 1) // 7 + 1,
        day_name=DAY_NAMES[d.weekday()], month_name=MONTH_NAMES[d.month - 1])


CAL_START = datetime.date(2024, 9, 24)
CAL = tuple(CAL_START + datetime.timedelta(days=i) for i in range(365))
CAL_END = CAL[-1]


def date_ok(info, year="", quarter="", month="", day_type="", payday=""):
    return ((not year or info.year == int(year))
            and (not quarter or info.quarter == int(quarter))
            and (not month or info.month == int(month))
            and (not day_type or info.weekend == (day_type == "weekend"))
            and (not payday or info.payday == (payday == "yes")))


def size_group(units):
    return "Heavy" if units >= 11 else "Light"


def age_band(age):
    return "18-29" if age < 30 else "30-39" if age < 40 else "40-49" if age < 50 else "50-60"


# ------------------------------------------------- reference data (source_db)

SRC_DATE = (r"""CASE WHEN o."deliveryDate" ~ '^\d{4}-' THEN to_date(o."deliveryDate", 'YYYY-MM-DD') """
            r"""ELSE to_date(o."deliveryDate", 'MM/DD/YYYY') END""")
SRC_VEHICLE = ("""CASE r."vehicleType" WHEN 'Bike' THEN 'Bicycle' WHEN 'Motorbike' THEN 'Motorcycle' """
               """ELSE r."vehicleType" END""")
SRC_GENDER = """CASE u.gender WHEN 'Female' THEN 'F' WHEN 'Male' THEN 'M' ELSE u.gender END"""
SRC_CATEGORY = ("""CASE lower(trim(p.category)) WHEN 'bag' THEN 'Bags' WHEN 'bags' THEN 'Bags' """
                """WHEN 'gadgets' THEN 'Gadgets' WHEN 'toy' THEN 'Toys' WHEN 'toys' THEN 'Toys' """
                """WHEN 'make up' THEN 'Makeup' WHEN 'makeup' THEN 'Makeup' ELSE trim(p.category) END""")
# Line value as the ETL defines it: quantity x list price rounded to cents, in whole cents.
SRC_LINE_CENTS = """oi.quantity * round(p.price::numeric, 2) * 100"""

Rider = namedtuple("Rider", "id name courier vehicle age band")
User = namedtuple("User", "id username country city gender")
Order = namedtuple("Order", "number date rider user units cents")


@lru_cache(maxsize=None)
def riders():
    rows = src("""SELECT r.id, r."firstName" || ' ' || r."lastName", c.name, %s, r.age
                  FROM "Riders" r JOIN "Couriers" c ON c.id = r."courierId" ORDER BY r.id""" % SRC_VEHICLE)
    return {int(i): Rider(int(i), name, courier, vehicle, int(age), age_band(int(age)))
            for i, name, courier, vehicle, age in rows}


@lru_cache(maxsize=None)
def users():
    rows = src("""SELECT u.id, u.username, u.country, u.city, %s FROM "Users" u ORDER BY u.id""" % SRC_GENDER)
    return {int(i): User(int(i), name, country, city, gender) for i, name, country, city, gender in rows}


@lru_cache(maxsize=None)
def username_to_id():
    return {u.username: u.id for u in users().values()}


@lru_cache(maxsize=None)
def orders():
    """Every source order with its normalised date, total units and total cents."""
    rows = src("""SELECT o."orderNumber", %s, o."deliveryRiderId", o."userId",
                         coalesce(i.q, 0), coalesce(i.v::bigint, 0)
                  FROM "Orders" o
                  LEFT JOIN (SELECT oi."OrderId" AS oid, sum(oi.quantity) AS q, sum(%s) AS v
                             FROM "OrderItems" oi JOIN "Products" p ON p.id = oi."ProductId"
                             GROUP BY 1) i ON i.oid = o.id
                  ORDER BY o.id""" % (SRC_DATE, SRC_LINE_CENTS))
    parsed = {}
    out = []
    for number, ds, rid, uid, units, cents in rows:
        if ds not in parsed:
            parsed[ds] = datetime.date.fromisoformat(ds)
        out.append(Order(number, parsed[ds], int(rid), int(uid), int(units), int(cents)))
    if NEGATIVE_CONTROL:
        out = out[1:]  # as if the warehouse had lost one order
    return tuple(out)


@lru_cache(maxsize=None)
def rider_day():
    """(date, rider id, size group) -> [orders, units]: the AGG_RIDER_DAY grain."""
    agg = defaultdict(lambda: [0, 0])
    for o in orders():
        cell = agg[(o.date, o.rider, size_group(o.units))]
        cell[0] += 1
        cell[1] += o.units
    return dict(agg)


@lru_cache(maxsize=None)
def vehicle_day():
    """(date, vehicle, size group) -> [orders, units, set of rider ids]."""
    agg = defaultdict(lambda: [0, 0, set()])
    rider_map = riders()
    for (d, rid, sg), (n, units) in rider_day().items():
        cell = agg[(d, rider_map[rid].vehicle, sg)]
        cell[0] += n
        cell[1] += units
        cell[2].add(rid)
    return dict(agg)


@lru_cache(maxsize=None)
def item_agg():
    """(category, date, vehicle, size group) -> (units, cents), straight from OrderItems."""
    rows = src("""WITH ord AS (SELECT o.id, %s AS d, o."deliveryRiderId" AS rid FROM "Orders" o),
                       oq AS (SELECT "OrderId" AS oid, sum(quantity) AS q FROM "OrderItems" GROUP BY 1)
                  SELECT %s, ord.d, %s, CASE WHEN oq.q >= 11 THEN 'Heavy' ELSE 'Light' END,
                         sum(oi.quantity), sum(%s)::bigint
                  FROM "OrderItems" oi
                  JOIN ord ON ord.id = oi."OrderId" JOIN oq ON oq.oid = oi."OrderId"
                  JOIN "Products" p ON p.id = oi."ProductId" JOIN "Riders" r ON r.id = ord.rid
                  GROUP BY 1, 2, 3, 4""" % (SRC_DATE, SRC_CATEGORY, SRC_VEHICLE, SRC_LINE_CENTS))
    out = {}
    for cat, ds, veh, sg, units, cents in rows:
        out[(cat, datetime.date.fromisoformat(ds), veh, sg)] = (int(units), int(cents))
    return out


@lru_cache(maxsize=None)
def source_products(category, year, quarter, month, vehicle, size_grp):
    """(category, product name) -> (units, cents) for one slice, from source_db."""
    where = []
    if category:
        where.append("%s = '%s'" % (SRC_CATEGORY, category.replace("'", "''")))
    if year:
        where.append("extract(year from ord.d) = %d" % int(year))
    if quarter:
        where.append("extract(quarter from ord.d) = %d" % int(quarter))
    if month:
        where.append("extract(month from ord.d) = %d" % int(month))
    if vehicle:
        assert vehicle in VEHICLES
        where.append("%s = '%s'" % (SRC_VEHICLE, vehicle))
    if size_grp:
        assert size_grp in SIZE_GROUPS
        where.append("(oq.q >= 11) = %s" % ("true" if size_grp == "Heavy" else "false"))
    rows = src("""WITH ord AS (SELECT o.id, %s AS d, o."deliveryRiderId" AS rid FROM "Orders" o),
                       oq AS (SELECT "OrderId" AS oid, sum(quantity) AS q FROM "OrderItems" GROUP BY 1)
                  SELECT %s, p.name, sum(oi.quantity), sum(%s)::bigint
                  FROM "OrderItems" oi
                  JOIN ord ON ord.id = oi."OrderId" JOIN oq ON oq.oid = oi."OrderId"
                  JOIN "Products" p ON p.id = oi."ProductId" JOIN "Riders" r ON r.id = ord.rid
                  %s GROUP BY 1, 2""" % (SRC_DATE, SRC_CATEGORY, SRC_LINE_CENTS,
                                        ("WHERE " + " AND ".join(where)) if where else ""))
    return {(cat, name): (int(units), int(cents)) for cat, name, units, cents in rows}


# --------------------------------------------------------------- R1 reference

def rank_desc(values):
    """RANK() over values ordered descending, for every value (list order kept)."""
    ordered = sorted(values, reverse=True)
    first = {}
    for i, v in enumerate(ordered):
        first.setdefault(v, i + 1)
    return [first[v] for v in values]


def r1_category(year="", quarter="", month="", vehicle="", size_group=""):
    totals = defaultdict(lambda: [0, 0])
    for (cat, d, veh, sg), (units, cents) in item_agg().items():
        info = dateinfo(d)
        if not date_ok(info, year, quarter, month):
            continue
        if (vehicle and veh != vehicle) or (size_group and sg != size_group):
            continue
        totals[cat][0] += units
        totals[cat][1] += cents
    cats = sorted(totals, key=lambda c: (-totals[c][1], c))
    grand_units = sum(totals[c][0] for c in cats)
    grand_cents = sum(totals[c][1] for c in cats)
    ranks = rank_desc([totals[c][1] for c in cats])
    rows = [{"category": c, "units": totals[c][0], "value": money(totals[c][1]),
             "value_share_pct": rnd(Fraction(100 * totals[c][1], grand_cents), 1) if grand_cents else None,
             "value_rank": r, "is_total": False} for c, r in zip(cats, ranks)]
    rows.append({"category": "All categories", "units": grand_units, "value": money(grand_cents),
                 "value_share_pct": rnd(Fraction(100 * grand_cents, grand_cents), 1) if grand_cents else None,
                 "value_rank": None, "is_total": True})
    return rows


def r1_product(category="", year="", quarter="", month="", vehicle="", size_group="", top_n=""):
    limit = int(top_n) if top_n else 10
    data = source_products(category, year, quarter, month, vehicle, size_group)
    by_cat = defaultdict(list)
    for (cat, name), (units, cents) in data.items():
        by_cat[cat].append((name, units, cents))
    rows = []
    for cat in sorted(by_cat):
        items = sorted(by_cat[cat], key=lambda t: (-t[2], t[0]))
        sub_units = sum(t[1] for t in items)
        sub_cents = sum(t[2] for t in items)
        ranks = rank_desc([t[2] for t in items])
        for (name, units, cents), rank in zip(items, ranks):
            if rank <= limit:
                rows.append({"category": cat, "product": name, "units": units, "value": money(cents),
                             "share_of_category_pct": rnd(Fraction(100 * cents, sub_cents), 1),
                             "rank_in_category": rank, "is_subtotal": False})
        rows.append({"category": cat, "product": "All products", "units": sub_units,
                     "value": money(sub_cents), "share_of_category_pct": rnd(Fraction(100), 1),
                     "rank_in_category": None, "is_subtotal": True})
    return rows


# --------------------------------------------------------------- R2 reference

def _rider_slice(year, quarter, month, courier, vehicle, band, size_grp):
    """Yield (rider, date, size group, orders, units) rows that pass every filter."""
    rider_map = riders()
    for (d, rid, sg), (n, units) in rider_day().items():
        r = rider_map[rid]
        if not date_ok(dateinfo(d), year, quarter, month):
            continue
        if (courier and r.courier != courier) or (vehicle and r.vehicle != vehicle):
            continue
        if (band and r.band != band) or (size_grp and sg != size_grp):
            continue
        yield r, d, sg, n, units


def r2_cube(year="", quarter="", month="", courier="", vehicle="", age_band="", size_group=""):
    cells = defaultdict(lambda: [0, 0, set()])
    for r, d, sg, n, units in _rider_slice(year, quarter, month, courier, vehicle, age_band, size_group):
        for key in ((r.courier, r.vehicle), (r.courier, None), (None, r.vehicle), (None, None)):
            cell = cells[key]
            cell[0] += n
            cell[1] += units
            cell[2].add(r.id)
    grand = cells[(None, None)][0]
    rows = []
    for (c, v), (n, units, rset) in cells.items():
        rows.append({
            "courier": c or "All couriers", "vehicle": v or "All vehicles", "orders": n, "units": units,
            "riders": len(rset), "orders_per_rider": rnd(Fraction(n, len(rset)), 0),
            "order_share_pct": rnd(Fraction(100 * n, grand), 1),
            "grouping_level": (1 if v is None else 0) + (2 if c is None else 0)})
    rows.sort(key=lambda r: (r["grouping_level"], r["courier"], r["vehicle"]))
    return rows


def r2_pivot(measure="", year="", quarter="", month="", courier="", vehicle="", age_band="", size_group=""):
    groups = defaultdict(lambda: {"orders": defaultdict(int), "riders": defaultdict(set)})
    for r, d, sg, n, units in _rider_slice(year, quarter, month, courier, vehicle, age_band, size_group):
        for key in (r.courier, None):
            groups[key]["orders"][r.vehicle] += n
            groups[key]["riders"][r.vehicle].add(r.id)

    def cell(g, vehicle_name):
        n = g["orders"].get(vehicle_name, 0)
        k = len(g["riders"].get(vehicle_name, ()))
        if measure == "per_rider":
            return rnd(Fraction(n, k), 0) if k else None
        return n

    rows = []
    for key in sorted(groups, key=lambda k: (k is None, k or "")):
        g = groups[key]
        total = sum(g["orders"].values())
        all_riders = set().union(*g["riders"].values())
        rows.append({
            "courier": key or "All couriers", "motorcycle": cell(g, "Motorcycle"),
            "bicycle": cell(g, "Bicycle"), "car": cell(g, "Car"), "trike": cell(g, "Trike"),
            "total": rnd(Fraction(total, len(all_riders)), 0) if measure == "per_rider" else total,
            "riders": len(all_riders), "is_total": key is None})
    return rows


def r2_rider(year="", quarter="", month="", courier="", vehicle="", age_band="", sort="", top_n=""):
    dates = [d for d in CAL if date_ok(dateinfo(d), year, quarter, month)]
    date_set = set(dates)
    per_day = defaultdict(int)       # (rider id, date) -> orders
    units_by = defaultdict(int)
    orders_by = defaultdict(int)
    for (d, rid, sg), (n, units) in rider_day().items():
        if d in date_set:
            per_day[(rid, d)] += n
            orders_by[rid] += n
            units_by[rid] += units
    chosen = [r for r in riders().values()
              if (not courier or r.courier == courier) and (not vehicle or r.vehicle == vehicle)
              and (not age_band or r.band == age_band)]
    n_riders = len(chosen)
    asc = sorted(orders_by.get(r.id, 0) for r in chosen)
    rows = []
    for r in chosen:
        o = orders_by.get(r.id, 0)
        active = sum(1 for d in dates if per_day.get((r.id, d), 0) > 0)
        rows.append({
            "workload_rank": 1 + n_riders - bisect_right(asc, o), "rider": r.name, "courier": r.courier,
            "vehicle": r.vehicle, "age_band": r.band, "orders": o, "units": units_by.get(r.id, 0),
            "active_days": active, "calendar_days": len(dates),
            "utilization_pct": rnd(Fraction(100 * active, len(dates)), 1) if dates else None,
            "avg_orders_per_active_day": rnd(Fraction(o, active), 1) if active else None,
            "peak_day_orders": max((per_day.get((r.id, d), 0) for d in dates), default=0),
            "workload_percentile": percent_rank_pct(bisect_left(asc, o) + 1, n_riders)})
    if sort == "least":
        rows.sort(key=lambda r: (r["orders"], r["rider"]))
    else:
        rows.sort(key=lambda r: (-r["orders"], r["rider"]))
    return rows, (int(top_n) if top_n else 20)


# --------------------------------------------------------------- R3 reference

@lru_cache(maxsize=None)
def customer_totals(year="", quarter=""):
    """user id -> [orders, units, cents] for the orders delivered in the period."""
    agg = defaultdict(lambda: [0, 0, 0])
    for o in orders():
        if not date_ok(dateinfo(o.date), year, quarter):
            continue
        cell = agg[o.user]
        cell[0] += 1
        cell[1] += o.units
        cell[2] += o.cents
    return dict(agg)


def _customer_slice(country, city, gender, year, quarter):
    user_map = users()
    return [(uid, vals, user_map[uid]) for uid, vals in customer_totals(year, quarter).items()
            if (not country or user_map[uid].country == country)
            and (not city or user_map[uid].city == city)
            and (not gender or user_map[uid].gender == gender)]


def r3_deciles(country="", gender="", year="", quarter=""):
    cents = sorted((vals[2] for _, vals, _ in _customer_slice(country, "", gender, year, quarter)),
                   reverse=True)
    n = len(cents)
    buckets = defaultdict(list)
    for pos, c in enumerate(cents):
        buckets[ntile_bucket(pos, n)].append(c)
    total = sum(cents)
    rows, running = [], 0
    for decile in sorted(buckets):
        vals = buckets[decile]
        running += sum(vals)
        rows.append({
            "decile": decile, "customers": len(vals), "value": money(sum(vals)),
            "value_share_pct": rnd(Fraction(100 * sum(vals), total), 1),
            "cumulative_share_pct": rnd(Fraction(100 * running, total), 1),
            "avg_value_per_customer": rnd(Fraction(sum(vals), 100 * len(vals)), 2),
            "min_customer_value": money(min(vals)), "max_customer_value": money(max(vals))})
    return rows


def r3_customer(country="", city="", gender="", decile="", year="", quarter="", top_n=""):
    sliced = _customer_slice(country, city, gender, year, quarter)
    n = len(sliced)
    asc = sorted(vals[2] for _, vals, _ in sliced)
    rows = []
    for uid, (orders_n, units, cents), user in sliced:
        first = n - bisect_right(asc, cents)          # 0-based first position among equals (desc)
        last = n - bisect_left(asc, cents) - 1
        possible = {ntile_bucket(p, n) for p in (first, last)}
        possible = set(range(min(possible), max(possible) + 1))
        rows.append({
            "value_rank": first + 1, "customer": user.username, "country": user.country,
            "city": user.city, "gender": user.gender, "orders": orders_n, "units": units,
            "value": money(cents), "avg_order_value": rnd(Fraction(cents, 100 * orders_n), 2),
            "decile": possible, "value_percentile": percent_rank_pct(bisect_left(asc, cents) + 1, n)})
    if decile:
        rows = [r for r in rows if int(decile) in r["decile"]]
    rows.sort(key=lambda r: (r["value_rank"], r["customer"]))
    return rows, (int(top_n) if top_n else 20)


def r3_geography(level="", country="", gender="", year="", quarter="", top_n=""):
    by_cell = defaultdict(lambda: [0, 0, 0])      # (location, gender) -> customers, orders, cents
    for uid, (orders_n, units, cents), user in _customer_slice(country, "", gender, year, quarter):
        loc = user.city if level == "city" else user.country
        cell = by_cell[(loc, user.gender)]
        cell[0] += 1
        cell[1] += orders_n
        cell[2] += cents
    locs = defaultdict(lambda: [0, 0, 0])
    genders = defaultdict(lambda: [0, 0, 0])
    grand = [0, 0, 0]
    for (loc, g), cell in by_cell.items():
        for acc in (locs[loc], genders[g], grand):
            for i in range(3):
                acc[i] += cell[i]
    loc_names = sorted(locs, key=lambda k: (-locs[k][2], k))
    ranks = dict(zip(loc_names, rank_desc([locs[k][2] for k in loc_names])))
    keep = [k for k in loc_names if ranks[k] <= (int(top_n) if top_n else 20)]

    def row(location, gender_label, cell, rank, grouping):
        return {"location": location, "gender": gender_label, "customers": cell[0], "orders": cell[1],
                "value": money(cell[2]), "value_per_customer": rnd(Fraction(cell[2], 100 * cell[0]), 2),
                "value_rank": rank, "grouping_level": grouping}

    rows = []
    for loc in keep:
        rows.append(row(loc, "All", locs[loc], ranks[loc], 1))
        for g in sorted(g for (l, g) in by_cell if l == loc):
            rows.append(row(loc, g, by_cell[(loc, g)], ranks[loc], 0))
    rows.append(row("All locations", "All", grand, None, 3))
    for g in sorted(genders):
        rows.append(row("All locations", g, genders[g], None, 2))
    return rows


# --------------------------------------------------------------- R4 reference

def daily_rows(year="", quarter="", month="", day_type="", payday="", vehicle="", size_group=""):
    """One entry per calendar day passing the day filters, zero-order days included."""
    cells = vehicle_day()
    out = []
    for d in CAL:
        info = dateinfo(d)
        if not date_ok(info, year, quarter, month, day_type, payday):
            continue
        n = units = 0
        riders_seen = set()
        for veh in VEHICLES:
            if vehicle and veh != vehicle:
                continue
            for sg in SIZE_GROUPS:
                if size_group and sg != size_group:
                    continue
                cell = cells.get((d, veh, sg))
                if cell:
                    n += cell[0]
                    units += cell[1]
                    riders_seen |= cell[2]
        out.append((d, info, n, units, len(riders_seen)))
    return out


def r4_rollup(year="", day_type="", payday="", vehicle="", size_group=""):
    acc = defaultdict(lambda: [0, 0, 0])          # key -> days, orders, units
    for d, info, n, units, _ in daily_rows(year, "", "", day_type, payday, vehicle, size_group):
        for key in ((info.year, info.quarter, info.month), (info.year, info.quarter, None),
                    (info.year, None, None), (None, None, None)):
            cell = acc[key]
            cell[0] += 1
            cell[1] += n
            cell[2] += units
    names = {0: "month", 1: "quarter", 2: "year", 3: "all"}
    rows = []
    for (y, q, m), (days, n, units) in acc.items():
        level = names[[m is not None, q is not None, y is not None].index(True)] if y is not None else "all"
        rows.append({"hierarchy_level": level, "year": y, "quarter": q, "month": m,
                     "month_name": MONTH_NAMES[m - 1] if m is not None else None, "days": days,
                     "orders": n, "units": units, "orders_per_day": rnd(Fraction(n, days), 1)})
    rows.sort(key=lambda r: (r["year"] is None, r["year"] or 0, r["quarter"] is None,
                             r["quarter"] or 0, r["month"] is None, r["month"] or 0))
    return rows


def r4_trend(level="", year="", quarter="", month="", day_type="", payday="", vehicle="", size_group=""):
    level = level or "month"
    acc = {}
    for d, info, n, units, _ in daily_rows(year, quarter, month, day_type, payday, vehicle, size_group):
        if level == "year":
            key, label = (info.year,), str(info.year)
        elif level == "quarter":
            key, label = (info.year, info.quarter), "%d Q%d" % (info.year, info.quarter)
        elif level == "week":
            key, label = (info.year, info.quarter, info.week), "%d W%02d" % (info.year, info.week)
        elif level == "day":
            key, label = (info.year, info.quarter, info.month, d), d.isoformat()
        else:
            key, label = (info.year, info.quarter, info.month), "%d %s" % (info.year, info.month_name)
        cell = acc.setdefault(key, {"label": label, "start": d, "days": 0, "orders": 0, "units": 0})
        cell["start"] = min(cell["start"], d)
        cell["days"] += 1
        cell["orders"] += n
        cell["units"] += units
    periods = sorted(acc.values(), key=lambda p: p["start"])
    opd = [rnd(Fraction(p["orders"], p["days"]), 1) for p in periods]
    rows = []
    for i, p in enumerate(periods):
        prev = opd[i - 1] if i else None
        window = opd[max(0, i - 6): i + 1]
        rows.append({
            "period_label": p["label"], "period_start": p["start"].isoformat(), "days": p["days"],
            "orders": p["orders"], "units": p["units"], "orders_per_day": opd[i],
            "change_vs_previous_pct": (rnd(Fraction(100) * (Fraction(opd[i]) - Fraction(prev)) / Fraction(prev), 1)
                                       if prev else None),
            "moving_avg_orders_per_day": rnd(sum(Fraction(v) for v in window) / len(window), 1)})
    return rows


def r4_weekday_pivot(year="", quarter="", payday="", vehicle="", size_group=""):
    groups = defaultdict(lambda: defaultdict(list))   # (year, month) -> weekday (0-6) -> orders per day
    for d, info, n, units, _ in daily_rows(year, quarter, "", "", payday, vehicle, size_group):
        groups[(info.year, info.month)][d.weekday()].append(n)
        groups[None][d.weekday()].append(n)

    def avg(values):
        return rnd(Fraction(sum(values), len(values)), 1) if values else None

    rows = []
    for key in sorted(groups, key=lambda k: (k is None, k or (0, 0))):
        g = groups[key]
        everything = [v for vals in g.values() for v in vals]
        rows.append({
            "month_label": "All months" if key is None else "%d %s" % (key[0], MONTH_NAMES[key[1] - 1]),
            "mon": avg(g.get(0, [])), "tue": avg(g.get(1, [])), "wed": avg(g.get(2, [])),
            "thu": avg(g.get(3, [])), "fri": avg(g.get(4, [])), "sat": avg(g.get(5, [])),
            "sun": avg(g.get(6, [])), "all_days": avg(everything), "is_total": key is None})
    return rows


def r4_busiest_days(year="", quarter="", month="", day_type="", payday="", vehicle="",
                    size_group="", sort="", top_n=""):
    days = daily_rows(year, quarter, month, day_type, payday, vehicle, size_group)
    mean = Fraction(sum(n for _, _, n, _, _ in days), len(days))
    ranks = rank_desc([n for _, _, n, _, _ in days])
    rows = []
    for (d, info, n, units, active), rank in zip(days, ranks):
        rows.append({
            "demand_rank": rank, "date": d.isoformat(), "day_name": info.day_name,
            "is_weekend": info.weekend, "is_payday": info.payday, "orders": n, "units": units,
            "active_riders": active,
            "orders_per_active_rider": rnd(Fraction(n, active), 1) if active else None,
            "vs_average_pct": rnd(100 * (n - mean) / mean, 1) if mean else None})
    if sort == "quietest":
        rows.sort(key=lambda r: (r["orders"], r["date"]))
    else:
        rows.sort(key=lambda r: (-r["orders"], r["date"]))
    return rows[: int(top_n) if top_n else 10]


if __name__ == "__main__":
    # `python dwsupport.py` prints the evidence header.
    info = preflight()
    print("date: %s" % datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    print("health: %s" % json.dumps(info["health"], sort_keys=True))
    for name, state in info["containers"].items():
        print("container %s: %s" % (name, state))
