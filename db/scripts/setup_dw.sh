#!/usr/bin/env bash
# setup_dw.sh — one-command data warehouse setup and verification.
# Thin bash shortcut over docker + psql against dw_db. The readiness gate itself
# lives in db/dw/validate/warehouse_readiness.sql (shared with the future ETL preflight).
# Idempotent: safe to re-run anytime, except --schema-only which replaces data.
# Usage (from repo root):
#   ./db/scripts/setup_dw.sh                # default: env + up + readiness report (no data touched)
#   ./db/scripts/setup_dw.sh --validate     # readiness checks only (needs healthy container)
#   ./db/scripts/setup_dw.sh --schema-only  # re-apply 01_dw_schema.sql (explicit, destructive)
#   macOS/Linux: ./db/scripts/setup_dw.sh [flags]
#   Windows (Git Bash or WSL): bash db/scripts/setup_dw.sh [flags]
#   Windows (CMD/PowerShell, no bash): run the equivalent directly —
#     Copy-Item .env.example .env; docker compose up -d --wait dw_db
#     Get-Content db/dw/validate/warehouse_readiness.sql | docker exec -i stadvdb-mco1-dw-db psql -X -At -U postgres -d dw_db -v ON_ERROR_STOP=1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Load .env if present; defaults match .env.example.
set -a
[ -f .env ] && source .env
set +a
DW_USER="${DW_USER:-postgres}"
DW_DB="${DW_DB:-dw_db}"
CONTAINER="stadvdb-mco1-dw-db"
R0_SQL="$ROOT/db/dw/validate/warehouse_readiness.sql"
COMMAND=""

usage() {
  sed -n '2,17p' "$ROOT/db/scripts/setup_dw.sh" | sed 's/^# \{0,1\}//'
}

die() {
  echo "error: $1" >&2
  echo "Run './db/scripts/setup_dw.sh --help' for usage." >&2
  exit 2
}

ensure_env() {
  # Never overwrite a member's local credentials.
  if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example (local-only, never commit it)."
  fi
}

ensure_up() {
  docker compose up -d --wait dw_db
}

require_healthy() {
  local status
  status="$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo missing)"
  if [ "$status" != "healthy" ]; then
    echo "error: $CONTAINER is '$status' (want 'healthy'). Run: docker compose logs dw_db" >&2
    exit 1
  fi
}

cmd_validate() {
  require_healthy
  [ -f "$R0_SQL" ] || die "readiness gate file missing: $R0_SQL"
  local result
  result="$(docker exec -i "$CONTAINER" psql -X -At -U "$DW_USER" -d "$DW_DB" \
    -v ON_ERROR_STOP=1 < "$R0_SQL")"
  echo "$result" | uv run --project db python -c "
import json, sys
report = json.loads(sys.stdin.read())
print(json.dumps(report, indent=2))
sys.exit(0 if report.get('passed') is True else 1)
"
}

cmd_schema_only() {
  # DESTRUCTIVE to data: DROP...CASCADE + CREATE ends with 9 empty tables.
  echo "warning: --schema-only replaces the warehouse schema (facts will be EMPTY)." >&2
  require_healthy
  docker exec -i "$CONTAINER" psql -U "$DW_USER" -d "$DW_DB" \
    -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/01_dw_schema.sql
  cmd_validate
}

cmd_default() {
  # Recovery and re-check path: never touches table contents.
  ensure_env
  ensure_up
  require_healthy
  cmd_validate
}

if [ "$#" -eq 0 ]; then
  cmd_default
  exit 0
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --validate) COMMAND="${COMMAND}validate " ;;
    --schema-only) COMMAND="${COMMAND}schema-only " ;;
    *) die "unexpected argument: $1" ;;
  esac
  shift
done

# shellcheck disable=SC2086
set -- $COMMAND
[ "$#" -eq 1 ] || die "give exactly one command per invocation"
case "$1" in
  validate) ensure_env; ensure_up; require_healthy; cmd_validate ;;
  schema-only) ensure_env; cmd_schema_only ;;
  *) die "unexpected command: $1" ;;
esac
