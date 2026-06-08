#!/usr/bin/env bash
# One-off player_analytics backfill for production or local DB.
#
# Required:
#   DATABASE_URL — Postgres connection string (Railway public URL from laptop)
#
# Optional:
#   SEASON — NFL season (default 2025)
#   SYNC_PLAYERS — set to 1 to refresh Sleeper fantasy_players catalog first
#
# Example (Railway public Postgres from Mac):
#   DATABASE_URL="$(railway variables --service Postgres --json \
#     | python3 -c "import sys,json; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")" \
#   ./scripts/run_fantasy_analytics_backfill.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is required" >&2
  exit 1
fi

SEASON="${SEASON:-2025}"
SYNC_FLAG="False"
if [[ "${SYNC_PLAYERS:-0}" == "1" ]]; then
  SYNC_FLAG="True"
fi

export PYTHONPATH=.
exec .venv/bin/python -c "
from app.services.etl.fantasy.sync_player_analytics import run
print(run(season=${SEASON}, sync_fantasy_players=${SYNC_FLAG}))
"
