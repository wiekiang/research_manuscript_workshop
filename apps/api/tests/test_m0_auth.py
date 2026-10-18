from __future__ import annotations

import pyotp
from conftest import PASSWORD, make_user


async def test_register_login_me(client):
    u = await make_user(client)
    r = await u.get("/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == u.email
    assert body["workspaces"][0]["role"] == "workspace_admin"
    assert "originality, validity, and integrity" in body["responsibility"]["message"]

    r = await client.post("/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["tenant_id"] == u.tenant_id


async def test_weak_password_and_duplicate_email(client):
    r = await client.post("/v1/auth/register", json={"email": "weak@example.org", "password": "short",
                                                     "display_name": "W"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    u = await make_user(client)
    r = await client.post("/v1/auth/register", json={"email": u.email, "password": PASSWORD, "display_name": "X"})
    assert r.status_code == 409


async def test_wrong_password_and_lockout(client):
    u = await make_user(client)
    for _ in range(10):
        r = await client.post("/v1/auth/login", json={"email": u.email, "password": "Wrong-password-123"})
        assert r.status_code == 401
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 423, "account must lock after repeated failures"


async def test_unknown_email_is_indistinguishable(client):
    r = await client.post("/v1/auth/login", json={"email": "nobody@example.org", "password": "Whatever-123x"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


async def test_refresh_rotation_and_reuse_detection(client):
    email = "rotate@example.org"
    await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": "R",
                                                 "workspace_name": "W"})
    first_rt = client.cookies.get("rp_rt")
    r = await client.post("/v1/auth/refresh", headers={"x-csrf-token": client.cookies.get("rp_csrf")})
    assert r.status_code == 200
    second_rt = client.cookies.get("rp_rt")
    assert second_rt and second_rt != first_rt
    # Replaying the rotated token revokes every session for the user.
    client.cookies.set("rp_rt", first_rt, path="/v1/auth")
    r = await client.post("/v1/auth/refresh")
    assert r.status_code == 401
    client.cookies.set("rp_rt", second_rt, path="/v1/auth")
    r = await client.post("/v1/auth/refresh")
    assert r.status_code == 401, "reuse detection must revoke the newer session too"


async def test_cookie_auth_requires_csrf_for_unsafe_methods(client):
    await client.post("/v1/auth/register", json={"email": "csrf@example.org", "password": PASSWORD,
                                                 "display_name": "C", "workspace_name": "W"})
    r = await client.get("/v1/auth/me")  # cookie auth, safe method
    assert r.status_code == 200
    r = await client.post("/v1/projects", json={"title": "No CSRF header", "responsibility_acknowledged": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = await client.post("/v1/projects", json={"title": "With CSRF header", "responsibility_acknowledged": True},
                          headers={"x-csrf-token": client.cookies.get("rp_csrf")})
    assert r.status_code == 201


async def test_mfa_enrolment_and_login(client):
    u = await make_user(client)
    r = await u.post("/v1/auth/mfa/setup")
    secret = r.json()["secret"]
    r = await u.post("/v1/auth/mfa/enable", json={"code": "000000"})
    assert r.status_code == 422
    r = await u.post("/v1/auth/mfa/enable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "mfa_required"
    r = await client.post("/v1/auth/login", json={"email": u.email, "password": PASSWORD,
                                                  "totp_code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200


async def test_admin_actions_require_mfa(client):
    admin = await make_user(client)
    other = await make_user(client, workspace=None)
    r = await admin.post("/v1/workspaces/current/members", json={"email": other.email, "role": "member"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_required"


async def test_invalid_and_tampered_tokens(client):
    r = await client.get("/v1/projects", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401
    u = await make_user(client)
    tampered = u.token[:-4] + ("AAAA" if not u.token.endswith("AAAA") else "BBBB")
    r = await client.get("/v1/projects", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


async def test_responsibility_ack_required_for_project(client):
    u = await make_user(client)
    r = await u.post("/v1/projects", json={"title": "Unacknowledged"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "responsibility_ack_required"
    assert "You are responsible" in r.json()["error"]["details"]["message"]
