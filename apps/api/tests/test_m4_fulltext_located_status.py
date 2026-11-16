"""Search-result ingest: a paper is ``located`` only when a full-text location is labelled ``kind="file"``
(rp_contracts.literature.FullTextLocation). Landing pages and unlabelled legacy links do not claim full text."""

from __future__ import annotations

import hashlib
import json

from conftest import make_project, make_user, service_token

PDF = {"url": "https://repo.example.org/paper.pdf", "kind": "file", "source": "openaire"}
LANDING = {"url": "https://doi.org/10.1234/landing", "kind": "landing_page", "source": "openaire"}
PUBLISHER = {"url": "https://publisher.example.org/article/1", "kind": "publisher_link", "source": "crossref"}
LEGACY = {"url": "http://arxiv.org/pdf/2006.12117", "source": "openaire"}  # stored before labels existed


async def _ingest(client, u, project_id: str, title: str, fulltext: list[dict]) -> None:
    """Run one search through the internal results endpoint, as the research worker does."""
    r = await u.post(f"/v1/projects/{project_id}/searches", json={"query": "provenance", "providers": ["openaire"]})
    assert r.status_code == 202, r.text
    run_id, task_id = r.json()["search_run_id"], r.json()["task"]["id"]
    h = await service_token(client, task_id)
    data = json.dumps({"query": "provenance"}).encode()
    res = (await client.post("/v1/internal/artifacts/reservations", headers=h, json={
        "project_id": project_id, "task_id": task_id, "input_manifest_hash": "c" * 64,
        "output_kind": "search_run_record", "media_type": "application/json", "slot": "record"})).json()
    await client.put(res["upload_url"], content=data, headers=h)
    art = (await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                             json={"content_hash": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})).json()
    r = await client.post(f"/v1/internal/projects/{project_id}/search-runs/{run_id}/results", headers=h, json={
        "provider_status": {"openaire": {"status": "ok", "retrieved": 1}},
        "results": [{"provider": "openaire", "rank": 1, "record": {"title": title, "fulltext": fulltext}}],
        "record_artifact_id": art["artifact_id"]})
    assert r.status_code == 200, r.text


async def _status(u, project_id: str, title: str) -> str:
    items = (await u.get(f"/v1/projects/{project_id}/papers")).json()["items"]
    return next(p for p in items if p["title"] == title)["fulltext_status"]


async def test_file_location_marks_paper_located(client):
    u = await make_user(client)
    p = await make_project(u)
    await _ingest(client, u, p["id"], "File paper", [LANDING, PDF])
    assert await _status(u, p["id"], "File paper") == "located"


async def test_landing_page_only_paper_is_not_located(client):
    u = await make_user(client)
    p = await make_project(u)
    await _ingest(client, u, p["id"], "Landing paper", [LANDING, PUBLISHER])
    assert await _status(u, p["id"], "Landing paper") == "none"


async def test_unlabelled_legacy_links_are_not_located(client):
    u = await make_user(client)
    p = await make_project(u)
    await _ingest(client, u, p["id"], "Legacy paper", [LEGACY])
    assert await _status(u, p["id"], "Legacy paper") == "none"


async def test_merge_upgrades_to_located_only_when_a_file_arrives(client):
    u = await make_user(client)
    p = await make_project(u)
    await _ingest(client, u, p["id"], "Merged paper", [LANDING])
    assert await _status(u, p["id"], "Merged paper") == "none"
    await _ingest(client, u, p["id"], "Merged paper", [LEGACY])  # unlabelled link still does not count
    assert await _status(u, p["id"], "Merged paper") == "none"
    await _ingest(client, u, p["id"], "Merged paper", [PDF])
    assert await _status(u, p["id"], "Merged paper") == "located"
