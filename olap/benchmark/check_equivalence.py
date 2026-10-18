"""Check that the rewritten queries in db/dw/optimize/queries return exactly the
same rows (and column types) as the originals in olap/queries, across many
randomized filter combinations. Covers the R2 and R4 rewrites that read
AGG_RIDER_DAY.

Run: uv run --project etl python olap/benchmark/check_equivalence.py
Exit code 1 on any mismatch.
"""
import sys, itertools, hashlib, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, "etl")
import run_benchmark as rb
conn = rb.connect("force_custom_plan")
orig, opt = Path("olap/queries"), Path("db/dw/optimize/queries")
V = ["", "Bicycle", "Motorcycle", "Car", "Trike"]; SG = ["", "Light", "Heavy"]
Y = ["", "2024", "2025"]; Q = ["", "1", "4"]; M = ["", "2", "12"]
C = ["", "FEDEZ", "JNT", "LBCD"]; A = ["", "18-29", "50-60"]
DT = ["", "weekday", "weekend"]; PD = ["", "yes", "no"]
def grid(**kw):
    ks = list(kw)
    for vals in itertools.product(*kw.values()):
        yield dict(zip(ks, vals))
random.seed(7)
def sample(g, n): g = list(g); return g if len(g) <= n else random.sample(g, n)
suites = {
 "r2_fleet_courier_workload/courier_vehicle_cube.sql": sample(grid(year=Y,quarter=Q,month=M,courier=C,vehicle=V,age_band=A,size_group=SG), 120),
 "r2_fleet_courier_workload/courier_vehicle_pivot.sql": [dict(p, measure=m) for p in sample(grid(year=Y,quarter=Q,month=M,courier=C,vehicle=V,age_band=A,size_group=SG), 60) for m in ("orders","per_rider")],
 "r2_fleet_courier_workload/rider.sql": [dict(p, sort=s, top_n=n) for p in sample(grid(year=Y,quarter=Q,month=M,courier=C,vehicle=V,age_band=A), 50) for s in ("most","least") for n in ("5","20")],
 "r4_demand_calendar/trend.sql": [dict(p, level=l) for p in sample(grid(year=Y,quarter=Q,month=M,day_type=DT,payday=PD,vehicle=V,size_group=SG), 40) for l in ("","year","quarter","month","week","day")],
 "r4_demand_calendar/rollup.sql": sample(grid(year=Y,day_type=DT,payday=PD,vehicle=V,size_group=SG), 80),
 "r4_demand_calendar/weekday_pivot.sql": sample(grid(year=Y,quarter=Q,payday=PD,vehicle=V,size_group=SG), 80),
 "r4_demand_calendar/busiest_days.sql": [dict(p, sort=s, top_n=n) for p in sample(grid(year=Y,quarter=Q,month=M,day_type=DT,payday=PD,vehicle=V,size_group=SG), 40) for s in ("busiest","quietest") for n in ("10","3")],
}
bad = total = no_rows = 0
def run(path, p):
    stmt, bound = rb.to_driver_sql(path.read_text(encoding="utf-8"), p)
    with conn.cursor() as cur:
        cur.execute(stmt, bound); r = cur.fetchall()
        return hashlib.md5(repr(r).encode()).hexdigest(), r, [d.type_code for d in cur.description]
for f, cases in suites.items():
    b = 0
    for p in cases:
        a1, r1, t1 = run(orig/f, p); a2, r2, t2 = run(opt/f, p)
        total += 1
        if not r1:
            no_rows += 1
        if a1 != a2 or t1 != t2:
            b += 1; bad += 1
            if b <= 2: print("MISMATCH", f, p, "types_equal" if t1 == t2 else "TYPES DIFFER")
    print(f"{f}: {len(cases)} param sets, {b} mismatches")
print(f"TOTAL {total} comparisons, {bad} mismatches ({no_rows} returned no rows)")
sys.exit(1 if bad else 0)
