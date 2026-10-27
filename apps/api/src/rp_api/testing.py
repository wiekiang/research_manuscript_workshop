"""Shared test harness (used by API tests and cross-service workflow tests).

Call `configure_test_env()` before importing any rp_api module that reads settings.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

TEST_DB = os.environ.get("RP_TEST_DB", "research_platform_test")
HOST = os.environ.get("RP_TEST_DB_HOST", "localhost:5433")
API_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "Correct-Horse-9-Battery"


def configure_test_env() -> Path:
    os.environ.setdefault("RP_ENVIRONMENT", "test")
    os.environ["RP_DATABASE_URL"] = f"postgresql+psycopg://rp_app:rp_app_dev@{HOST}/{TEST_DB}"
    os.environ["RP_DATABASE_URL_OWNER"] = f"postgresql+psycopg://rp_owner:rp_owner_dev@{HOST}/{TEST_DB}"
    os.environ["RP_DATABASE_URL_SYSTEM"] = f"postgresql+psycopg://rp_system:rp_system_dev@{HOST}/{TEST_DB}"
    os.environ["RP_DATABASE_URL_INGEST"] = f"postgresql+psycopg://rp_ingest:rp_ingest_dev@{HOST}/{TEST_DB}"
    os.environ.setdefault("RP_OBJECT_STORE_BACKEND", "local")
    tmp = Path(os.environ.get("RP_TEST_TMP") or tempfile.mkdtemp(prefix="rp-test-"))
    os.environ["RP_TEST_TMP"] = str(tmp)
    os.environ["RP_OBJECT_STORE_LOCAL_PATH"] = str(tmp / "objects")
    os.environ["RP_SIGNING_KEY_PATH"] = str(tmp / "jwt.pem")
    os.environ["RP_RATE_LIMIT_AUTH_PER_MINUTE"] = "10000"
    os.environ["RP_WORKER_ENVIRONMENT"] = "test"
    os.environ["RP_WORKER_API_BASE_URL"] = "http://testserver"
    return tmp


def _require_throwaway_target(host: str, owner_url: str | None) -> None:
    """Refuse destructive resets unless both the DSN target and the owner URL name the throwaway test cluster.

    The database name is taken from RP_DATABASE_URL_OWNER (set by configure_test_env from HOST and TEST_DB),
    so the equality check compares two independently supplied names instead of TEST_DB with itself.
    """
    if not owner_url:
        raise RuntimeError(f"refusing to reset on host {host!r}: RP_DATABASE_URL_OWNER is not set, so the "
                           "database to drop cannot be verified")
    try:
        parts = urlsplit(owner_url)
        url_host = f"{parts.hostname}:{parts.port}" if parts.port else (parts.hostname or "")
    except ValueError as exc:
        raise RuntimeError(f"refusing to reset on host {host!r}: RP_DATABASE_URL_OWNER is not parseable ({exc})") from exc
    db = (parts.path or "").lstrip("/")
    name, _, port = host.partition(":")
    if (name != "localhost" or port != "5433" or url_host != "localhost:5433"
            or db != TEST_DB or not db.endswith("_test")):
        raise RuntimeError(f"refusing to reset database {db!r} on host {host!r} (owner URL host {url_host!r}): "
                           f"only {TEST_DB!r} (a *_test database) on localhost:5433 may be dropped")


def reset_database() -> None:
    import psycopg

    _require_throwaway_target(HOST, os.environ.get("RP_DATABASE_URL_OWNER"))
    owner = f"postgresql://rp_owner:rp_owner_dev@{HOST}/{TEST_DB}"
    with psycopg.connect(owner, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public AUTHORIZATION rp_owner")
        conn.execute("GRANT USAGE ON SCHEMA public TO rp_app, rp_system, rp_ingest, PUBLIC")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    env = dict(os.environ, RP_MIGRATION_URL=os.environ["RP_DATABASE_URL_OWNER"])
    proc = subprocess.run([sys.executable, "-m", "alembic", "-c", str(API_ROOT / "alembic.ini"), "upgrade", "head"],
                          cwd=API_ROOT, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"migration failed:\n{proc.stderr[-4000:]}")


import httpx  # noqa: E402


class UserHandle:
    def __init__(self, client: httpx.AsyncClient, body: dict, email: str, password: str):
        self.client = client
        self.token = body["access_token"]
        self.user_id = body["user"]["id"]
        self.tenant_id = body["tenant_id"]
        self.email = email
        self.password = password

    @property
    def h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def get(self, path, **kw):
        return await self.client.get(path, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def post(self, path, json=None, **kw):
        return await self.client.post(path, json=json, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def patch(self, path, json=None, **kw):
        return await self.client.patch(path, json=json, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def put(self, path, content=None, **kw):
        return await self.client.put(path, content=content, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def delete(self, path, **kw):
        return await self.client.delete(path, headers={**self.h, **kw.pop("headers", {})}, **kw)


async def make_user(client: httpx.AsyncClient, *, workspace: str | None = "Lab", email: str | None = None) -> UserHandle:
    email = email or f"r-{uuid.uuid4().hex[:10]}@example.org"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Dr Test",
                                                     "workspace_name": workspace})
    assert r.status_code == 201, r.text
    return UserHandle(client, r.json(), email, PASSWORD)


async def make_project(u: UserHandle, title: str = "Robust evaluation of retrieval methods") -> dict:
    r = await u.post("/v1/projects", json={"title": title, "topic": "information retrieval",
                                           "responsibility_acknowledged": True})
    assert r.status_code == 201, r.text
    return r.json()


async def make_task(tenant_id: str, project_id: str | None, kind: str = "cfp_import", params: dict | None = None) -> str:
    """Create a workflow task directly (domain endpoints create them in later milestones)."""
    from rp_api.db.engine import session_scope
    from rp_api.db.models.core import WorkflowTask

    tid = uuid.uuid4()
    async with session_scope("system") as db:
        db.add(WorkflowTask(id=tid, tenant_id=uuid.UUID(tenant_id), project_id=uuid.UUID(project_id) if project_id else None,
                            kind=kind, state="queued", idempotency_key=f"test:{tid}", input_manifest_hash="0" * 64,
                            params=params or {}, requested_by="test", temporal_workflow_id=f"task-{tid}"))
        await db.commit()
    return str(tid)


async def service_token(client: httpx.AsyncClient, task_id: str) -> dict:
    r = await client.post("/v1/internal/auth/token", json={"client_id": "research-worker",
                                                           "client_secret": "dev-research-worker-secret",
                                                           "task_id": task_id})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
