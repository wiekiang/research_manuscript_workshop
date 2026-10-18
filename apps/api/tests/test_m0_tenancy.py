"""Cross-tenant access must fail safely at the API and at the database (RLS) layer."""

from __future__ import annotations

import uuid

import pytest
from conftest import make_project, make_task, make_user, service_token
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError


async def test_cross_tenant_project_access_is_404(client):
    a = await make_user(client)
    b = await make_user(client)
    p = await make_project(a)
    for path in (f"/v1/projects/{p['id']}", f"/v1/projects/{p['id']}/events", f"/v1/projects/{p['id']}/members",
                 f"/v1/projects/{p['id']}/artifacts", f"/v1/projects/{p['id']}/contribution-ledger",
                 f"/v1/projects/{p['id']}/usage"):
        r = await b.get(path)
        assert r.status_code == 404, (path, r.status_code, r.text)
    r = await b.get("/v1/projects")
    assert all(item["id"] != p["id"] for item in r.json()["items"])
    r = await b.post(f"/v1/projects/{p['id']}/pause", json={"expected_version": 1})
    assert r.status_code == 404


async def test_rls_blocks_reads_and_writes_across_tenants(client):
    from rp_api.db.engine import session_scope
    from rp_api.db.models.core import Project

    a = await make_user(client)
    b = await make_user(client)
    p = await make_project(a)
    async with session_scope("app", tenant_id=uuid.UUID(b.tenant_id), user_id=uuid.UUID(b.user_id)) as db:
        rows = (await db.execute(select(Project).where(Project.id == uuid.UUID(p["id"])))).scalars().all()
        assert rows == []
        res = await db.execute(text("UPDATE projects SET title='hijacked' WHERE id=:i"), {"i": p["id"]})
        assert res.rowcount == 0
    # Inserting a row for another tenant violates the WITH CHECK policy.
    async with session_scope("app", tenant_id=uuid.UUID(b.tenant_id), user_id=uuid.UUID(b.user_id)) as db:
        with pytest.raises(DBAPIError):
            await db.execute(text(
                "INSERT INTO projects (id, tenant_id, version, title, state, owner_id, budget_cap_cents, "
                "stage_budget_limits, currency, readiness_stage) VALUES (gen_random_uuid(), :t, 1, 'x', 'CREATED', :o, "
                "1, '{}', 'USD', 'research_proposal')"), {"t": a.tenant_id, "o": a.user_id})
    # No tenant context at all: nothing is visible.
    async with session_scope("app") as db:
        assert (await db.execute(select(Project))).scalars().all() == []


async def test_app_role_cannot_touch_private_or_global_writes(client):
    from rp_api.db.engine import session_scope

    a = await make_user(client)
    async with session_scope("app", tenant_id=uuid.UUID(a.tenant_id), user_id=uuid.UUID(a.user_id)) as db:
        with pytest.raises(ProgrammingError):
            await db.execute(text("SELECT * FROM auth_sessions"))
    async with session_scope("app", tenant_id=uuid.UUID(a.tenant_id), user_id=uuid.UUID(a.user_id)) as db:
        with pytest.raises(ProgrammingError):
            await db.execute(text("SELECT * FROM secret_records"))
    async with session_scope("app", tenant_id=uuid.UUID(a.tenant_id), user_id=uuid.UUID(a.user_id)) as db:
        rows = (await db.execute(text("SELECT key FROM provider_definitions"))).scalars().all()
        assert "crossref" in rows
        with pytest.raises(ProgrammingError):
            await db.execute(text("UPDATE provider_definitions SET enabled = true WHERE key = 'elicit'"))


async def test_append_only_tables(client):
    from rp_api.db.engine import session_scope

    a = await make_user(client)
    await make_project(a)
    for role in ("app", "system"):
        async with session_scope(role, tenant_id=uuid.UUID(a.tenant_id), user_id=uuid.UUID(a.user_id)) as db:
            with pytest.raises(DBAPIError):
                await db.execute(text("UPDATE project_events SET event_type = 'tampered'"))
        async with session_scope(role, tenant_id=uuid.UUID(a.tenant_id), user_id=uuid.UUID(a.user_id)) as db:
            with pytest.raises(DBAPIError):
                await db.execute(text("DELETE FROM audit_log"))


async def test_service_token_scoped_to_its_task_project(client):
    a = await make_user(client)
    p1 = await make_project(a, "Project one for scope test")
    p2 = await make_project(a, "Project two for scope test")
    task = await make_task(a.tenant_id, p1["id"])
    h = await service_token(client, task)
    r = await client.get(f"/v1/internal/projects/{p1['id']}", headers=h)
    assert r.status_code == 200
    r = await client.get(f"/v1/internal/projects/{p2['id']}", headers=h)
    assert r.status_code == 403
    r = await client.post("/v1/internal/artifacts/reservations", headers=h, json={
        "project_id": p2["id"], "task_id": task, "input_manifest_hash": "a" * 64, "output_kind": "generic_json",
        "media_type": "application/json"})
    assert r.status_code == 403


async def test_other_tenant_task_token_cannot_reach_project(client):
    a = await make_user(client)
    b = await make_user(client)
    pa = await make_project(a)
    pb = await make_project(b)
    task_b = await make_task(b.tenant_id, pb["id"])
    h = await service_token(client, task_b)
    r = await client.get(f"/v1/internal/projects/{pa['id']}", headers=h)
    assert r.status_code in (403, 404)


async def test_user_tokens_cannot_use_internal_routes(client):
    a = await make_user(client)
    p = await make_project(a)
    r = await a.post(f"/v1/internal/projects/{p['id']}/transitions", json={
        "requested_state": "TARGET_REVIEW", "expected_project_version": 1, "idempotency_key": "user-attempt-1"})
    assert r.status_code == 403
    r = await client.post("/v1/internal/auth/token", json={"client_id": "research-worker", "client_secret": "wrong",
                                                           "task_id": str(uuid.uuid4())})
    assert r.status_code == 401
