"""Model gateway policy side (provider gates, data classification, data-flow attestation, idempotent caching) and
cost controls (thresholds, hard stop, explicit cap change)."""

from __future__ import annotations

import uuid

from conftest import make_project, make_task, make_user, service_token
from sqlalchemy import text


def _auth_body(**kw):
    body = {"agent": "cfp_extractor", "purpose": "generation", "provider": "fixture", "model": "fixture-1",
            "prompt_version": "cfp-extract-1", "prompt_hash": "a" * 64, "idempotency_key": f"inv-{uuid.uuid4()}",
            "data_classification": "public", "data_kinds": ["cfp_documents"], "max_tokens": 1000,
            "estimated_cost_cents": 10}
    body.update(kw)
    return body


async def _set_provider(key: str, **cols):
    from rp_api.db.engine import session_scope

    async with session_scope("ingest") as db:
        sets = ", ".join(f"{k} = :{k}" for k in cols)
        await db.execute(text(f"UPDATE provider_definitions SET {sets} WHERE key = :key"), {**cols, "key": key})
        await db.commit()


async def test_pending_provider_is_denied_and_recorded(client):
    u = await make_user(client)
    p = await make_project(u)
    h = await service_token(client, await make_task(u.tenant_id, p["id"]))
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h,
                          json=_auth_body(provider="anthropic", model="claude-sonnet-5-5"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "model_call_denied"
    usage = (await u.get(f"/v1/projects/{p['id']}/usage")).json()
    assert usage["model_invocations"][0]["status"] == "denied"


async def test_enabled_provider_requires_owner_data_flow_attestation(client):
    await _set_provider("anthropic", enabled=True, gate_status="development_only")
    try:
        u = await make_user(client)
        p = await make_project(u)
        h = await service_token(client, await make_task(u.tenant_id, p["id"]))
        r = await client.post("/v1/internal/model-invocations/authorize", headers=h,
                              json=_auth_body(provider="anthropic", model="claude-sonnet-5-5"))
        assert r.status_code == 403 and r.json()["error"]["code"] == "data_flow_not_permitted"
        r = await u.post(f"/v1/projects/{p['id']}/data-flow", json={
            "provider_key": "anthropic", "data_kinds": ["cfp_documents"], "max_classification": "public",
            "attestation_accepted": True})
        assert r.status_code == 201
        r = await client.post("/v1/internal/model-invocations/authorize", headers=h,
                              json=_auth_body(provider="anthropic", model="claude-sonnet-5-5"))
        assert r.status_code == 200
        # An attestation for public data does not cover an unpublished manuscript.
        r = await client.post("/v1/internal/model-invocations/authorize", headers=h, json=_auth_body(
            provider="anthropic", model="claude-sonnet-5-5", data_kinds=["unpublished_manuscript"],
            data_classification="internal"))
        assert r.status_code == 403
        # Restricted data is never sent to a provider that does not allow it.
        r = await client.post("/v1/internal/model-invocations/authorize", headers=h, json=_auth_body(
            provider="anthropic", model="claude-sonnet-5-5", data_classification="restricted"))
        assert r.status_code == 403
    finally:
        await _set_provider("anthropic", enabled=False, gate_status="pending")


async def test_completed_invocation_is_cached_for_retries(client):
    u = await make_user(client)
    p = await make_project(u)
    h = await service_token(client, await make_task(u.tenant_id, p["id"]))
    body = _auth_body()
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h, json=body)
    inv = r.json()["invocation_id"]
    r = await client.post(f"/v1/internal/model-invocations/{inv}/complete", headers=h, json={
        "status": "succeeded", "input_tokens": 100, "output_tokens": 50, "actual_cost_cents": 3,
        "response": {"rules": []}})
    assert r.status_code == 200
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h, json=body)
    assert r.json()["status"] == "cached" and r.json()["response"] == {"rules": []}
    usage = (await u.get(f"/v1/projects/{p['id']}/usage")).json()
    assert usage["budget"]["spent_cents"] == 3


async def test_budget_thresholds_and_hard_stop(client):
    u = await make_user(client)
    r = await u.post("/v1/projects", json={"title": "Tight budget project", "budget_cap_cents": 100,
                                           "responsibility_acknowledged": True})
    p = r.json()
    h = await service_token(client, await make_task(u.tenant_id, p["id"]))
    for cost in (55, 30):
        r = await client.post("/v1/internal/model-invocations/authorize", headers=h,
                              json=_auth_body(estimated_cost_cents=cost))
        inv = r.json()["invocation_id"]
        await client.post(f"/v1/internal/model-invocations/{inv}/complete", headers=h, json={
            "status": "succeeded", "input_tokens": 1, "output_tokens": 1, "actual_cost_cents": cost, "response": {}})
    usage = (await u.get(f"/v1/projects/{p['id']}/usage")).json()
    assert sorted(a["threshold_pct"] for a in usage["alerts"]) == [50, 80]
    notes = (await u.get("/v1/notifications")).json()["items"]
    assert any("80%" in n["title"] for n in notes)
    # 85 spent: a 20-cent call would exceed the cap and must be refused before it runs.
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h, json=_auth_body(estimated_cost_cents=20))
    assert r.status_code == 422 and r.json()["error"]["code"] == "budget_exceeded"
    usage = (await u.get(f"/v1/projects/{p['id']}/usage")).json()
    assert 100 in [a["threshold_pct"] for a in usage["alerts"]]
    # Only an explicit owner decision raises the cap.
    r = await u.post(f"/v1/projects/{p['id']}/budget", json={"new_cap_cents": 500, "expected_version": p["version"],
                                                              "rationale": "extend extraction"})
    assert r.status_code == 200 and r.json()["cap_cents"] == 500
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h, json=_auth_body(estimated_cost_cents=20))
    assert r.status_code == 200


async def test_secret_store_encrypts_and_scopes_owner(client):
    from rp_api.db.engine import session_scope
    from rp_api.security.secrets import secrets_service

    owner = uuid.uuid4()
    sid = await secrets_service.store("provider_key", "sk-test-PLAINTEXT-123", owner_user_id=owner)
    async with session_scope("system") as db:
        raw = (await db.execute(text("SELECT ciphertext FROM secret_records WHERE id = :i"), {"i": sid})).scalar_one()
    assert b"PLAINTEXT" not in bytes(raw)
    assert await secrets_service.read(sid, "provider_key", owner_user_id=owner) == "sk-test-PLAINTEXT-123"
    import pytest

    with pytest.raises(PermissionError):
        await secrets_service.read(sid, "provider_key", owner_user_id=uuid.uuid4())
    await secrets_service.destroy(sid)
    with pytest.raises(KeyError):
        await secrets_service.read(sid, "provider_key", owner_user_id=owner)


async def test_claude_cli_provider_is_refused_outside_local(client):
    """The personal CLI-login provider is local-only; any other environment (here: test) must deny it."""
    u = await make_user(client)
    p = await make_project(u)
    h = await service_token(client, await make_task(u.tenant_id, p["id"]))
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h,
                          json=_auth_body(provider="claude_cli", model="account-default"))
    assert r.status_code == 403 and "local-only" in r.json()["error"]["message"]
