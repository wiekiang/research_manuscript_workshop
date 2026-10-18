"""Researcher-chosen AI provider: API-key connection, per-project choice, key release to workers, and enforcement."""

from __future__ import annotations

import uuid

from conftest import make_project, make_task, make_user, service_token
from sqlalchemy import text

KEY = "sk-ant-test-" + "x" * 32


async def test_connect_key_choose_provider_and_enforce(client):
    u = await make_user(client)
    p = await make_project(u)
    consent = (await u.get("/v1/me/model-connections")).json()["anthropic"]["consent_text"]
    r = await u.put("/v1/me/model-connections/anthropic", json={"api_key": "not-a-key-but-long-enough", "consent_accepted": True,
                                                                "consent_text": consent})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_key_format"
    r = await u.put("/v1/me/model-connections/anthropic", json={"api_key": KEY, "consent_accepted": True, "consent_text": "ok"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "consent_required"

    opts = {o["key"]: o for o in (await u.get(f"/v1/projects/{p['id']}/model-provider")).json()["options"]}
    assert not opts["claude_cli"]["available"] and "locally" in opts["claude_cli"]["reason"], "tests run with environment=test"
    assert not opts["anthropic"]["available"] and "connect your Anthropic API key" in opts["anthropic"]["reason"]
    r = await u.put(f"/v1/projects/{p['id']}/model-provider", json={"provider": "anthropic"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "provider_unavailable"

    r = await u.put("/v1/me/model-connections/anthropic", json={"api_key": KEY, "consent_accepted": True, "consent_text": consent})
    assert r.status_code == 200 and r.json() == {**r.json(), "connected": True, "key_hint": "…xxxx"}
    assert KEY not in r.text, "the key is never returned"
    from rp_api.db.engine import session_scope

    async with session_scope("system") as db:
        raw = (await db.execute(text("SELECT ciphertext FROM secret_records WHERE purpose='anthropic_api_key'"))).scalars().all()
    assert raw and all(KEY.encode() not in bytes(c) for c in raw), "stored encrypted"

    r = await u.put(f"/v1/projects/{p['id']}/model-provider", json={"provider": "anthropic"})
    assert r.status_code == 200 and r.json()["selected"] == "anthropic"

    # The worker for this project receives the owner's key; calls to another provider are refused for this project.
    h = await service_token(client, await make_task(u.tenant_id, p["id"]))
    got = (await client.get("/v1/internal/model-provider", headers=h)).json()
    assert got == {"provider": "anthropic", "api_key": KEY}
    body = {"agent": "cfp_extractor", "purpose": "generation", "provider": "fixture", "model": "fixture-1",
            "prompt_version": "v1", "prompt_hash": "a" * 64, "idempotency_key": f"inv-{uuid.uuid4()}",
            "data_classification": "public", "data_kinds": ["cfp_documents"], "max_tokens": 100, "estimated_cost_cents": 1}
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h, json=body)
    assert r.status_code == 403 and "selected anthropic" in r.json()["error"]["message"]
    r = await client.post("/v1/internal/model-invocations/authorize", headers=h,
                          json={**body, "provider": "anthropic", "model": "claude-opus-5-5", "idempotency_key": f"inv-{uuid.uuid4()}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "data_flow_not_permitted", \
        "the owner's key passes the provider gate outside production, but the data-flow approval is still required"

    # Another user's project never gets this key; a coauthor cannot change the choice.
    other = await make_user(client)
    op = await make_project(other)
    h2 = await service_token(client, await make_task(other.tenant_id, op["id"]))
    assert (await client.get("/v1/internal/model-provider", headers=h2)).json() == {"provider": None}

    r = await u.delete("/v1/me/model-connections/anthropic")
    assert r.status_code == 200
    got = (await client.get("/v1/internal/model-provider", headers=h)).json()
    assert "api_key" not in got and "not connected" in got["error"]
