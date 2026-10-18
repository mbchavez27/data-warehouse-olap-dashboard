#!/usr/bin/env bash
# End-to-end check of the report API against the live warehouse (dw_db).
#
# 1. For each report level and filter set, calls the running API, then runs the
#    original, unoptimized SQL (evidence/benchmark/original-queries) directly in
#    dw_db with the parameters the API echoed back. Rows and column names must
#    match, in order.
# 2. Checks that bad requests get the expected status (400 for invalid filters,
#    404 for an unknown report or level) and that a SQL-looking filter is bound
#    as a plain value.
#
# Needs curl, node and docker. The API must already be running:
#   docker compose --profile app up -d --no-deps api
#
# Run from the repository root:
#   bash olap/benchmark/api_e2e_check.sh | tee evidence/benchmark/api-e2e/results.txt
# Exit code 0 when everything matches, 1 on any mismatch or unexpected response,
# 2 when the API is not reachable.
set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd) || exit 2
cd "$ROOT" || exit 2
API=${API:-http://localhost:8080}
DW=${DW_CONTAINER:-stadvdb-mco1-dw-db}
ORIG=evidence/benchmark/original-queries
BASE="$API/api/reports"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
problems=0

if ! curl -fsS -m 5 "$API/api/health" > "$WORK/health.json"; then
  echo "API not reachable at $API" >&2
  exit 2
fi
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "health: $(cat "$WORK/health.json")"
echo

# Compares one API response with the original SQL's rows (JSON from json_agg).
cat > "$WORK/cmp.js" <<'EOF'
const fs = require('fs');
const [apiPath, origPath] = process.argv.slice(2);
const api = JSON.parse(fs.readFileSync(apiPath, 'utf8'));
const raw = fs.readFileSync(origPath, 'utf8').trim();
const orig = raw ? JSON.parse(raw) || [] : [];
const apiRows = api.rows || [];
// Keys are sorted so that key order inside a row cannot cause a false mismatch.
const sortKeys = (v) => (v && typeof v === 'object' && !Array.isArray(v))
  ? Object.keys(v).sort().reduce((o, k) => { o[k] = v[k]; return o; }, {})
  : v;
const canon = (rows) => JSON.stringify(rows, (k, v) => sortKeys(v));
const apiCols = (api.columns || []).map(c => c.name);
const origCols = orig.length ? Object.keys(orig[0]) : null;
const colsOk = origCols === null ? 'n/a (no rows)'
  : (JSON.stringify(apiCols) === JSON.stringify(origCols) ? 'same' : 'DIFFERENT');
const equal = canon(apiRows) === canon(orig);
console.log(`  ${equal ? 'rows equal' : 'ROWS DIFFER'}: api=${apiRows.length} orig=${orig.length}, columns ${colsOk}`);
if (!equal) {
  const n = Math.max(apiRows.length, orig.length);
  for (let i = 0; i < n; i++) {
    if (canon([apiRows[i]]) !== canon([orig[i]])) {
      console.log('  first difference at row', i, '\n  api :', canon([apiRows[i]]), '\n  orig:', canon([orig[i]]));
      break;
    }
  }
}
process.exit(equal && colsOk !== 'DIFFERENT' ? 0 : 1);
EOF

# One request per line: API path, original SQL file, query string.
CASES=(
"r1/category|r1_product_category_value/category.sql|"
"r1/category|r1_product_category_value/category.sql|year=2025"
"r1/category|r1_product_category_value/category.sql|year=2025&vehicle=Motorcycle&size_group=Heavy"
"r1/category|r1_product_category_value/category.sql|year=2024&quarter=4&month=12&vehicle=Car"
"r1/product|r1_product_category_value/product.sql|category=Toys&top_n=5"
"r1/product|r1_product_category_value/product.sql|year=2025&quarter=1&vehicle=Trike&top_n=3"
"r2/courier_vehicle_cube|r2_fleet_courier_workload/courier_vehicle_cube.sql|"
"r2/courier_vehicle_cube|r2_fleet_courier_workload/courier_vehicle_cube.sql|year=2024&courier=JNT&age_band=30-39"
"r2/courier_vehicle_pivot|r2_fleet_courier_workload/courier_vehicle_pivot.sql|measure=per_rider&year=2025&size_group=Light"
"r2/courier_vehicle_pivot|r2_fleet_courier_workload/courier_vehicle_pivot.sql|measure=orders&courier=LBCD"
"r2/rider|r2_fleet_courier_workload/rider.sql|sort=least&top_n=20&vehicle=Car"
"r2/rider|r2_fleet_courier_workload/rider.sql|year=2025&quarter=2&top_n=10"
"r3/deciles|r3_customer_value_distribution/deciles.sql|"
"r3/deciles|r3_customer_value_distribution/deciles.sql|gender=F&year=2025"
"r3/geography|r3_customer_value_distribution/geography.sql|level=country&gender=M"
"r3/geography|r3_customer_value_distribution/geography.sql|level=city&country=Philippines"
"r3/customer|r3_customer_value_distribution/customer.sql|top_n=20"
"r3/customer|r3_customer_value_distribution/customer.sql|country=Philippines&decile=10&top_n=5"
"r4/rollup|r4_demand_calendar/rollup.sql|"
"r4/rollup|r4_demand_calendar/rollup.sql|year=2024&day_type=weekend"
"r4/trend|r4_demand_calendar/trend.sql|level=day&year=2025&payday=yes"
"r4/trend|r4_demand_calendar/trend.sql|level=week&quarter=3&vehicle=Bicycle"
"r4/weekday_pivot|r4_demand_calendar/weekday_pivot.sql|year=2025&vehicle=Bicycle"
"r4/busiest_days|r4_demand_calendar/busiest_days.sql|sort=quietest&top_n=3&size_group=Heavy"
"r4/busiest_days|r4_demand_calendar/busiest_days.sql|"
)

echo "== report levels: API vs original SQL on $DW"
n=0; equal=0
for c in "${CASES[@]}"; do
  IFS='|' read -r api file qs <<< "$c"
  n=$((n+1)); out="$WORK/c$n"
  echo "[$n] $api ${qs:-(no filters)}"
  read -r code secs < <(curl -s -G -m 120 -o "$out.api.json" -w '%{http_code} %{time_total}' "$BASE/$api${qs:+?$qs}")
  echo "  http=$code api=${secs}s"
  if [ "$code" != 200 ]; then
    problems=$((problems+1)); echo "  API error body: $(cat "$out.api.json")"; continue
  fi

  # Parameters exactly as the API bound them (empty string = all).
  mapfile -t PAIRS < <(node -e 'const p = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).params; for (const k in p) console.log(k + "=" + p[k])' "$out.api.json")
  VARGS=(); for p in "${PAIRS[@]}"; do VARGS+=(-v "$p"); done

  { echo "SELECT json_agg(t) FROM ("; sed -z 's/;[[:space:]]*$//' "$ORIG/$file"; echo; echo ") t;"; } > "$out.sql"
  if ! docker exec -i "$DW" psql -X -At -U postgres -d dw_db -v ON_ERROR_STOP=1 "${VARGS[@]}" < "$out.sql" > "$out.orig.json" 2> "$out.err"; then
    problems=$((problems+1)); echo "  ORIGINAL SQL FAILED: $(cat "$out.err")"; continue
  fi

  if node "$WORK/cmp.js" "$out.api.json" "$out.orig.json"; then
    equal=$((equal+1))
  else
    problems=$((problems+1))
  fi
done

echo
echo "== error handling and literal filters"
check_status() {  # label, expected HTTP status, URL, [curl options]
  local label=$1 want=$2
  shift 2
  local got
  got=$(curl -s -G -m 30 -o "$WORK/neg.json" -w '%{http_code}' "$@")
  if [ "$got" = "$want" ]; then
    echo "  ok   $label -> $got"
  else
    problems=$((problems+1))
    echo "  FAIL $label -> $got, expected $want: $(cat "$WORK/neg.json")"
  fi
}
check_status "unknown parameter" 400 "$BASE/r1/category?bogus=1"
check_status "year outside the allowed values" 400 "$BASE/r1/category?year=2023"
check_status "unknown level" 404 "$BASE/r1/nope"
check_status "unknown report" 404 "$BASE/r9/category"

# If the filter were concatenated into the SQL, OR '1'='1' would return every
# customer. Zero rows, with the text echoed back, shows it was bound as a value.
INJ="x' OR '1'='1"
body=$(curl -s -G -m 30 "$BASE/r3/customer" --data-urlencode "country=$INJ")
if printf '%s' "$body" | INJ="$INJ" node -e 'const b = JSON.parse(require("fs").readFileSync(0, "utf8")); process.exit(b.rowCount === 0 && b.params.country === process.env.INJ ? 0 : 1)'; then
  echo "  ok   SQL-looking country filter is bound as text (0 rows)"
else
  problems=$((problems+1))
  echo "  FAIL SQL-looking country filter was not bound as text: $body"
fi

echo
echo "== summary: report levels $n, equal $equal, problems $problems"
[ "$problems" -eq 0 ]
