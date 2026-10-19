#!/bin/bash
# deploy/export-dw-dump.sh
# ──────────────────────────────────────────────────────────────────────
# Run on your LOCAL machine (where the ETL has already loaded the DW).
# Exports the full data-warehouse database to a compressed SQL dump that
# the production PostgreSQL container restores automatically on first boot.
#
# Usage (from the repository root):
#   bash deploy/export-dw-dump.sh
#
# Output:  deploy/seed/01_restore_dw.sql.gz   (~40-80 MB)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SEED_DIR="$REPO_ROOT/deploy/seed"

# Load the .env so we know what port/credentials the local compose uses.
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

DW_PORT="${DW_PORT:-5434}"
DW_DB="${DW_DB:-dw_db}"
DW_USER="${DW_USER:-postgres}"

echo "📦 Exporting data-warehouse from localhost:$DW_PORT/$DW_DB …"

# Make sure the container is running.
docker compose -f "$REPO_ROOT/docker-compose.yml" up -d --wait dw_db

mkdir -p "$SEED_DIR"

# pg_dump produces a plain SQL script (schema + data).
# The .sql.gz extension makes PostgreSQL's init entrypoint gunzip and run it.
docker compose -f "$REPO_ROOT/docker-compose.yml" exec -T dw_db \
  pg_dump -U "$DW_USER" -d "$DW_DB" \
    --clean --if-exists --no-owner --no-privileges \
  | gzip > "$SEED_DIR/01_restore_dw.sql.gz"

SIZE=$(du -h "$SEED_DIR/01_restore_dw.sql.gz" | cut -f1)
echo "✅ Dump saved to deploy/seed/01_restore_dw.sql.gz ($SIZE)"
echo ""
echo "Next steps:"
echo "  1.  git add deploy/seed/01_restore_dw.sql.gz"
echo "  2.  git commit -m 'chore: add DW seed dump for production deploy'"
echo "  3.  git push origin main"
echo "  4.  On the VPS:  docker compose -f docker-compose.deploy.yml up -d --build"
