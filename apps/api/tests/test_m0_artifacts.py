"""Artifact reservation/commit protocol: crash/retry safety, conflicts, reconciliation, immutability."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

import pytest
from conftest import make_project, make_task, make_user, service_token
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def _body(obj) -> bytes:
    return json.dumps(obj, sort_keys=True).encode()


async def _reserve(client, h, project_id, task_id, imh="b" * 64, kind="generic_json", slot="0"):
    r = await client.post("/v1/internal/artifacts/reservations", headers=h, json={
        "project_id": project_id, "task_id": task_id, "input_manifest_hash": imh, "output_kind": kind,
        "media_type": "application/json", "slot": slot})
    assert r.status_code == 200, r.text
    return r.json()


async def test_full_publication_lifecycle_and_idempotent_commit(client):
    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    data = _body({"rules": [1, 2, 3]})
    digest = hashlib.sha256(data).hexdigest()

    res = await _reserve(client, h, p["id"], task)
    again = await _reserve(client, h, p["id"], task)
    assert again["reservation_id"] == res["reservation_id"], "same key must return the same reservation"
    assert res["status"] == "ARTIFACT_RESERVED"

    r = await client.put(res["upload_url"], content=data, headers=h)
    assert r.json()["status"] == "CONTENT_UPLOADED"
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": digest, "size_bytes": len(data)})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["created"] is True and first["status"] == "AVAILABLE_TO_WORKFLOW"

    # Retry after a lost response: same artifact, nothing duplicated.
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": digest, "size_bytes": len(data)})
    assert r.json()["artifact_id"] == first["artifact_id"] and r.json()["created"] is False
    # Reserve again after commit returns the committed artifact id.
    again = await _reserve(client, h, p["id"], task)
    assert again["artifact_id"] == first["artifact_id"]

    listing = (await u.get(f"/v1/projects/{p['id']}/artifacts")).json()["items"]
    assert [a["id"] for a in listing].count(first["artifact_id"]) == 1


async def test_conflicting_hash_for_committed_key_is_rejected(client):
    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    data = _body({"v": 1})
    res = await _reserve(client, h, p["id"], task, imh="c" * 64)
    await client.put(res["upload_url"], content=data, headers=h)
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
    assert r.status_code == 200
    other = _body({"v": 2})
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": hashlib.sha256(other).hexdigest(), "size_bytes": len(other)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "artifact_hash_conflict"
    r = await client.put(res["upload_url"], content=other, headers=h)
    assert r.status_code == 409


async def test_reported_hash_must_match_uploaded_bytes(client):
    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    res = await _reserve(client, h, p["id"], task, imh="d" * 64)
    await client.put(res["upload_url"], content=b'{"real": true}', headers=h)
    lie = hashlib.sha256(b'{"fake": true}').hexdigest()
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": lie, "size_bytes": 14})
    assert r.status_code == 409 and r.json()["error"]["code"] == "hash_mismatch"


async def test_crash_after_upload_before_commit_stays_invisible_then_retry(client):
    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    data = _body({"evidence": "x"})
    digest = hashlib.sha256(data).hexdigest()
    res = await _reserve(client, h, p["id"], task, imh="e" * 64)
    await client.put(res["upload_url"], content=data, headers=h)
    # "Crash": no commit. Nothing is visible to users, reviews or approvals.
    assert (await u.get(f"/v1/projects/{p['id']}/artifacts")).json()["items"] == []
    # An uncommitted output cannot satisfy a transition request.
    r = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json={
        "requested_state": "TARGET_REVIEW", "expected_project_version": 1, "idempotency_key": "crash-test-0001",
        "output_artifact_ids": [res["reservation_id"]]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "uncommitted_outputs"
    # Worker restarts: same reservation key, same bytes -> commit succeeds once.
    res2 = await _reserve(client, h, p["id"], task, imh="e" * 64)
    assert res2["reservation_id"] == res["reservation_id"]
    await client.put(res2["upload_url"], content=data, headers=h)
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": digest, "size_bytes": len(data)})
    assert r.status_code == 200
    assert len((await u.get(f"/v1/projects/{p['id']}/artifacts")).json()["items"]) == 1


async def test_reconciler_removes_orphans_and_expires_reservations(client):
    from rp_api.services.reconciler import reconcile
    from rp_api.storage import get_store

    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    res = await _reserve(client, h, p["id"], task, imh="f" * 64)
    await client.put(res["upload_url"], content=b"{}", headers=h)
    store = get_store()
    orphan = f"tmp/{u.tenant_id}/{uuid.uuid4()}"
    store.put_bytes(orphan, b"orphan bytes", "application/octet-stream")
    old = time.time() - 10 * 24 * 3600
    os.utime(store._path(orphan), (old, old))  # type: ignore[attr-defined]

    report = await reconcile()
    assert orphan in report.deleted_orphans
    assert res["reservation_id"] in report.pending_uploads, "a fresh uploaded reservation is kept for retry"
    assert not store.exists(orphan)

    from rp_api.db.engine import session_scope

    async with session_scope("system") as db:
        await db.execute(text("UPDATE artifact_reservations SET expires_at = now() - interval '1 day' WHERE id = :i"),
                         {"i": res["reservation_id"]})
        await db.commit()
    report = await reconcile(retention_seconds=0)
    assert res["reservation_id"] in report.expired_reservations


async def test_artifact_metadata_is_immutable_in_database(client):
    from rp_api.db.engine import session_scope

    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    data = b'{"immutable": true}'
    res = await _reserve(client, h, p["id"], task, imh="1" * 64)
    await client.put(res["upload_url"], content=data, headers=h)
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
    aid = r.json()["artifact_id"]
    async with session_scope("app", tenant_id=uuid.UUID(u.tenant_id)) as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE artifacts SET content_hash = repeat('0', 64) WHERE id = :i"), {"i": aid})
    async with session_scope("app", tenant_id=uuid.UUID(u.tenant_id)) as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("DELETE FROM artifacts WHERE id = :i"), {"i": aid})
    async with session_scope("app", tenant_id=uuid.UUID(u.tenant_id)) as db:
        # Freshness may change (dependency invalidation), content may not.
        res = await db.execute(text("UPDATE artifacts SET freshness = 'stale' WHERE id = :i"), {"i": aid})
        assert res.rowcount == 1


async def test_kind_and_media_type_validation(client):
    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    r = await client.post("/v1/internal/artifacts/reservations", headers=h, json={
        "project_id": p["id"], "task_id": task, "input_manifest_hash": "2" * 64, "output_kind": "generic_json",
        "media_type": "application/x-sh"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "media_type_not_permitted"
    r = await client.post("/v1/internal/artifacts/reservations", headers=h, json={
        "project_id": p["id"], "task_id": task, "input_manifest_hash": "2" * 64, "output_kind": "protocol",
        "media_type": "application/json"})
    assert r.status_code == 403, "workers cannot mint human-owned artifact kinds such as protocols"


async def test_signed_download_url_expiry_and_tamper(client):
    from rp_api.storage import sign_download, verify_download

    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    data = b'{"download": true}'
    res = await _reserve(client, h, p["id"], task, imh="3" * 64)
    await client.put(res["upload_url"], content=data, headers=h)
    aid = (await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h, json={
        "content_hash": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})).json()["artifact_id"]
    url = (await u.get(f"/v1/artifacts/{aid}/download-url")).json()["url"]
    r = await client.get(url)
    assert r.status_code == 200 and r.content == data
    r = await client.get(url.replace("?t=", "?t=9"))
    assert r.status_code == 403
    expired = sign_download(uuid.UUID(u.tenant_id), uuid.UUID(aid), -5)
    assert not verify_download(uuid.UUID(u.tenant_id), uuid.UUID(aid), expired)
    other = await make_user(client)
    r = await other.get(f"/v1/artifacts/{aid}/download-url")
    assert r.status_code == 404
