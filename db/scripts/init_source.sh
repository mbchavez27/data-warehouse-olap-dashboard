#!/usr/bin/env bash
# Applies db/source/init/01_source_schema.sql to source_db.
# Idempotent: safe to re-run anytime (DDL is DROP...CASCADE + CREATE).
# Usage (from repo root): ./db/scripts/init_source.sh
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

# 1. Fail fast unless the container is healthy (no blind sleeps).
STATUS="$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo missing)"
if [ "$STATUS" != "healthy" ]; then
  echo "error: $CONTAINER is '$STATUS' (want 'healthy'). Run: docker compose up -d" >&2
  exit 1
fi

# 2. Apply DDL via the read-only init mount inside the container
#    (no local psql required — everything runs through docker exec).
docker exec -i "$CONTAINER" psql -U "$SOURCE_USER" -d "$SOURCE_DB" \
  -v ON_ERROR_STOP=1 \
  -f /docker-entrypoint-initdb.d/01_source_schema.sql

# 3. Verify: list tables + row counts (expect 6 tables, 0 rows each).
docker exec "$CONTAINER" psql -U "$SOURCE_USER" -d "$SOURCE_DB" -c "\dt"
for t in Couriers Riders Users Products Orders OrderItems; do
  docker exec "$CONTAINER" psql -U "$SOURCE_USER" -d "$SOURCE_DB" -t \
    -c "SELECT '$t', count(*) FROM \"$t\";"
done
