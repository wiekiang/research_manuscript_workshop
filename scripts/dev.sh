#!/usr/bin/env bash
# Local development stack: infra containers, migrations, API, outbox relay and Temporal workers.
#   scripts/dev.sh up      start everything (logs in var/log/)
#   scripts/dev.sh down    stop app processes (containers keep running; use `docker compose -f infra/compose.yaml down`)
#   scripts/dev.sh status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/var/log"; RUN="$ROOT/var/run"
mkdir -p "$LOG" "$RUN"
cd "$ROOT"

start() { # name, command...
  local name=$1; shift
  if [[ -f "$RUN/$name.pid" ]] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "$name already running"; return; fi
  nohup "$@" > "$LOG/$name.log" 2>&1 &
  echo $! > "$RUN/$name.pid"; echo "started $name (pid $!)"
}

case "${1:-up}" in
  up)
    docker compose -f infra/compose.yaml up -d
    until docker compose -f infra/compose.yaml exec -T postgres pg_isready -U rp_owner -d research_platform >/dev/null 2>&1; do sleep 1; done
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
