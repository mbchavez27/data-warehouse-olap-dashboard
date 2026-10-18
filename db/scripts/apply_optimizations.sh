#!/usr/bin/env bash
# apply_optimizations.sh — apply the Phase 2 query optimizations to dw_db.
# Runs db/dw/optimize/01_indexes.sql, 02_config.sql and 03_preagg.sql in order.
# Idempotent (indexes use IF NOT EXISTS, views are dropped and rebuilt), so it is
# also the refresh step: run it after every ETL load and after `--rebuild`.
# Usage (from repo root):
#   bash db/scripts/apply_optimizations.sh
set -euo pipefail

# Git Bash (MSYS) rewrites Unix-style paths before they reach `docker exec`.
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

set -a
[ -f .env ] && source .env
set +a
DW_USER="${DW_USER:-postgres}"
DW_DB="${DW_DB:-dw_db}"
CONTAINER="stadvdb-mco1-dw-db"

for f in 01_indexes.sql 02_config.sql 03_preagg.sql; do
  echo "== db/dw/optimize/$f"
  docker cp "db/dw/optimize/$f" "$CONTAINER:/tmp/$f"
  docker exec "$CONTAINER" psql -X -U "$DW_USER" -d "$DW_DB" -v ON_ERROR_STOP=1 -f "/tmp/$f"
done
echo "optimizations applied"
