"""rp-api command line: serve | migrate | relay | reconcile | export-contracts."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path


def _alembic(*args: str) -> int:
    root = Path(__file__).resolve().parents[2]
    return subprocess.call([sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), *args], cwd=root)


def main() -> None:
    parser = argparse.ArgumentParser(prog="rp-api")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser("migrate")
    sub.add_parser("relay", help="dispatch outbox events to Temporal")
    sub.add_parser("reconcile", help="run the artifact reconciler once")
    exp = sub.add_parser("export-contracts", help="write OpenAPI + JSON Schemas into contracts/")
    exp.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("rp_api.main:app", host=args.host, port=args.port, reload=args.reload, proxy_headers=True)
    elif args.cmd == "migrate":
        raise SystemExit(_alembic("upgrade", "head"))
    elif args.cmd == "relay":
        from .relay import run_forever

        asyncio.run(run_forever())
    elif args.cmd == "reconcile":
        from .services.reconciler import reconcile

        print(json.dumps(asyncio.run(reconcile()).as_dict(), indent=2))
    elif args.cmd == "export-contracts":
        from .contracts_export import export

        export(args.out)
