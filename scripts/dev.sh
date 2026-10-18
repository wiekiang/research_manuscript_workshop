#!/usr/bin/env bash
# Local development app processes: migrations, API, outbox relay and Temporal workers (logs in var/log/).
# Infrastructure is NOT started here (the Docker setup was removed): PostgreSQL 17 + pgvector, an S3-compatible
# object store and a Temporal server must already be reachable at the RP_* / RP_WORKER_* settings.
#   scripts/dev.sh up      start the app processes
#   scripts/dev.sh down    stop them
#   scripts/dev.sh status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/var/log"; RUN="$ROOT/var/run"
mkdir -p "$LOG" "$RUN"
cd "$ROOT"
# Settings (database URLs, credentials) come from the git-ignored .env at the repo root; see .env.example.
if [[ -f .env ]]; then set -a; source .env; set +a; fi

start() { # name, command...
  local name=$1; shift
  if [[ -f "$RUN/$name.pid" ]] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "$name already running"; return; fi
  nohup "$@" > "$LOG/$name.log" 2>&1 &
  echo $! > "$RUN/$name.pid"; echo "started $name (pid $!)"
}

case "${1:-up}" in
  up)
    uv run python -c "import psycopg,os; psycopg.connect(os.environ.get('RP_DATABASE_URL_OWNER','postgresql://rp_owner:rp_owner_dev@localhost:5433/research_platform').replace('+psycopg','')).close()" \
      || { echo "PostgreSQL is not reachable; start your database (see docs/DEPLOYMENT.md) and retry." >&2; exit 1; }
    (cd apps/api && uv run alembic upgrade head)
    start api uv run rp-api serve --host 127.0.0.1 --port 8000
    start relay uv run rp-api relay
    start worker uv run rp-worker run --queues research-main,controlled-fetch,latex-sandbox,experiment-sandbox
    uv run rp-worker schedules || true
    echo "API http://localhost:8000/v1/docs   Temporal UI http://localhost:8233"
    ;;
  down)
    for f in "$RUN"/*.pid; do [[ -f "$f" ]] && { kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; echo "stopped $(basename "$f" .pid)"; }; done
    ;;
  status)
    for f in "$RUN"/*.pid; do [[ -f "$f" ]] && { n=$(basename "$f" .pid); kill -0 "$(cat "$f")" 2>/dev/null && echo "$n running" || echo "$n dead"; }; done
    ;;
esac
