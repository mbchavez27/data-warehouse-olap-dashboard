#!/usr/bin/env bash
# setup_source.sh — one-command source database setup and verification.
# Thin bash shortcut over the `uv run --project db` importer commands
# (see docs/database/source-database-setup.md, the cross-platform contract).
# Idempotent: safe to re-run anytime, except --schema-only which replaces data.
# Usage (from repo root):
#   ./db/scripts/setup_source.sh                                  # default: env + up + test + validate (no ZIP needed)
#   ./db/scripts/setup_source.sh --archive <zip> --reset          # full fresh-clone path (== --all)
#   ./db/scripts/setup_source.sh --all --archive <zip> --reset
#   ./db/scripts/setup_source.sh --test | --validate | --schema-only
#   ./db/scripts/setup_source.sh --verify --archive <zip> [--output <json>]
#   ./db/scripts/setup_source.sh --import --archive <zip> --reset [--output <json>]
#   macOS/Linux: ./db/scripts/setup_source.sh [flags]
#   Windows (Git Bash or WSL): bash db/scripts/setup_source.sh [flags]
#   Windows (CMD/PowerShell, no bash): use the uv commands directly —
#     uv run --project db pytest db/source/importer
#     uv run --project db python db/source/importer/cli.py verify --archive "C:\absolute\path\MCO1_dataset_ecommerce.zip"
#     Copy-Item .env.example .env; docker compose up -d --wait source_db
#     uv run --project db python db/source/importer/cli.py import --archive "C:\absolute\path\MCO1_dataset_ecommerce.zip" --reset
#     uv run --project db python db/source/importer/cli.py validate
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Load .env if present; defaults match .env.example.
set -a
[ -f .env ] && source .env
set +a
SOURCE_USER="${SOURCE_USER:-postgres}"
SOURCE_DB="${SOURCE_DB:-source_db}"
CONTAINER="stadvdb-mco1-source-db"

ARCHIVE=""
OUTPUT=""
RESET=0
COMMAND=""

usage() {
  sed -n '2,16p' "$ROOT/db/scripts/setup_source.sh" | sed 's/^# \{0,1\}//'
}

die() {
  echo "error: $1" >&2
  echo "Run './db/scripts/setup_source.sh --help' for usage." >&2
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
  docker compose up -d --wait source_db
}

require_healthy() {
  local status
  status="$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo missing)"
  if [ "$status" != "healthy" ]; then
    echo "error: $CONTAINER is '$status' (want 'healthy'). Run: docker compose logs source_db" >&2
    exit 1
  fi
}

cmd_test() {
  uv run --project db pytest db/source/importer
}

cmd_verify() {
  [ -n "$ARCHIVE" ] || die "--verify requires --archive <MCO1_dataset_ecommerce.zip>"
  if [ -n "$OUTPUT" ]; then
    uv run --project db python db/source/importer/cli.py verify --archive "$ARCHIVE" --output "$OUTPUT"
  else
    uv run --project db python db/source/importer/cli.py verify --archive "$ARCHIVE"
  fi
}

cmd_import() {
  [ -n "$ARCHIVE" ] || die "--import requires --archive <MCO1_dataset_ecommerce.zip>"
  [ "$RESET" -eq 1 ] || die "--import is destructive and requires explicit --reset"
  if [ -n "$OUTPUT" ]; then
    uv run --project db python db/source/importer/cli.py import --archive "$ARCHIVE" --reset --output "$OUTPUT"
  else
    uv run --project db python db/source/importer/cli.py import --archive "$ARCHIVE" --reset
  fi
}

cmd_validate() {
  require_healthy
  if [ -n "$OUTPUT" ]; then
    uv run --project db python db/source/importer/cli.py validate --output "$OUTPUT"
  else
    uv run --project db python db/source/importer/cli.py validate
  fi
}

cmd_schema_only() {
  # DESTRUCTIVE to data: DROP...CASCADE + CREATE ends with 6 tables, 0 rows each.
  echo "warning: --schema-only replaces all six source tables with EMPTY schema." >&2
  require_healthy
  docker exec -i "$CONTAINER" psql -U "$SOURCE_USER" -d "$SOURCE_DB" \
    -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/01_source_schema.sql
  docker exec "$CONTAINER" psql -U "$SOURCE_USER" -d "$SOURCE_DB" -c "\dt"
  for t in Couriers Riders Users Products Orders OrderItems; do
    docker exec "$CONTAINER" psql -U "$SOURCE_USER" -d "$SOURCE_DB" -t \
      -c "SELECT '$t', count(*) FROM \"$t\";"
  done
}

cmd_default() {
  # No-ZIP recovery and re-check path: never touches table contents.
  ensure_env
  ensure_up
  require_healthy
  cmd_test
  # Keep the import report intact: flow validation goes to the revalidation file.
  OUTPUT="${OUTPUT:-evidence/source-db-revalidation.json}"
  cmd_validate
}

cmd_all() {
  [ -n "$ARCHIVE" ] || die "--all requires --archive <MCO1_dataset_ecommerce.zip>"
  [ "$RESET" -eq 1 ] || die "--all replaces all six tables and requires explicit --reset"
  ensure_env
  ensure_up
  require_healthy
  cmd_test
  cmd_verify
  cmd_import
  # Keep the just-written import report intact: flow validation goes to the
  # revalidation file (standalone --validate without --output still uses the
  # default report path, matching cli.py behavior).
  OUTPUT="${OUTPUT:-evidence/source-db-revalidation.json}"
  cmd_validate
  echo "Done. Open evidence/source-import-report.json and confirm top-level passed is true."
}

if [ "$#" -eq 0 ]; then
  cmd_default
  exit 0
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --test) COMMAND="${COMMAND}test " ;;
    --verify) COMMAND="${COMMAND}verify " ;;
    --import) COMMAND="${COMMAND}import " ;;
    --validate) COMMAND="${COMMAND}validate " ;;
    --schema-only) COMMAND="${COMMAND}schema-only " ;;
    --all) COMMAND="${COMMAND}all " ;;
    --archive)
      [ "$#" -ge 2 ] || die "missing value for --archive"
      ARCHIVE="$2"; shift ;;
    --output)
      [ "$#" -ge 2 ] || die "missing value for --output"
      OUTPUT="$2"; shift ;;
    --reset) RESET=1 ;;
    *) die "unexpected argument: $1" ;;
  esac
  shift
done

# Bare --archive without a command means the full fresh-clone path.
if [ -z "$COMMAND" ]; then
  if [ -n "$ARCHIVE" ]; then
    COMMAND="all "
  else
    die "no command given (try --help)"
  fi
fi

# One command per invocation; --all already sequences the full chain.
# shellcheck disable=SC2086
set -- $COMMAND
[ "$#" -eq 1 ] || die "give exactly one command per invocation (or use --all for the full chain)"
case "$1" in
  test) ensure_env; ensure_up; require_healthy; cmd_test ;;
  verify)
    [ -n "$ARCHIVE" ] || die "--verify requires --archive <MCO1_dataset_ecommerce.zip>"
    ensure_env; ensure_up; require_healthy; cmd_verify ;;
  import)
    [ -n "$ARCHIVE" ] || die "--import requires --archive <MCO1_dataset_ecommerce.zip>"
    [ "$RESET" -eq 1 ] || die "--import is destructive and requires explicit --reset"
    ensure_env; ensure_up; require_healthy; cmd_import ;;
  validate) ensure_env; ensure_up; require_healthy; cmd_validate ;;
  schema-only) ensure_env; cmd_schema_only ;;
  all) cmd_all ;;
  *) die "unexpected command: $1" ;;
esac
