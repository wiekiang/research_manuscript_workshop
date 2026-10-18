#!/usr/bin/env bash
# Run every backend suite; exit non-zero on the first failing suite (use before committing).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
uv run ruff check -q apps services contracts tests workers
(cd apps/api && uv run pytest tests -q -p no:cacheprovider)
RP_WORKER_ENVIRONMENT=test uv run pytest contracts/tests services/research/tests workers -q -p no:cacheprovider
uv run pytest tests/workflows -q -p no:cacheprovider --timeout 600
echo "ALL BACKEND SUITES PASSED"
