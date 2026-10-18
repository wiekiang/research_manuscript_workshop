"""M2 acceptance: the curated conference set ranks relevant tracks (precision@k / NDCG recorded), discovery only
reaches verified official sources through controlled fetch, and CFP monitoring detects changes conditionally."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import drain_outbox, make_project, make_user
from sqlalchemy import delete
from temporalio.worker import Worker

from rp_contracts.ranking import ResearchProfile, ndcg_at_k, precision_at_k, score_candidate
from rp_contracts.tasks import QUEUE_FETCH, QUEUE_RESEARCH
from rp_research.fetch.text import extract_html
from rp_research.registry import ACTIVITIES, WORKFLOWS, load_features

pytestmark = pytest.mark.temporal
FIX = Path(__file__).resolve().parents[2] / "services/research/src/rp_research/fixtures/cfp"
REPO = Path(__file__).resolve().parents[2]
load_features()

PROFILE = {"topics": ["reproducibility of data-intensive experiments", "provenance capture", "lineage systems",
                      "benchmark evaluation"], "methods": ["benchmark", "empirical"], "lead_time_weeks": 10,
           "preferred_publishers": ["ACM"]}
CORPUS = {  # series_key -> (fixture, host, adjudicated gain)
    "icrds": ("icrds2027.html", "icrds.example.org", 3.0),
    "wdp": ("dataprov2026.html", "wdp.example.org", 2.0),  # relevant but its deadline has passed
    "dlsc": ("mlsys2027.html", "dlsc.example.org", 1.0),
    "iccs": ("chem2027.html", "iccs.example.org", 0.0),
}


def test_ranking_evaluation_precision_and_ndcg():
    now = datetime(2026, 10, 18, tzinfo=UTC)
    profile = ResearchProfile(**PROFILE)
    results = []
    for key, (fname, _, _) in CORPUS.items():
        lt = extract_html((FIX / fname).read_bytes())
        due = {"icrds": datetime(2027, 1, 22, 11, 59, tzinfo=UTC), "wdp": datetime(2026, 9, 2, 11, 59, tzinfo=UTC),
               "dlsc": datetime(2027, 2, 11, 11, 59, tzinfo=UTC), "iccs": datetime(2027, 3, 1, 23, 59, tzinfo=UTC)}[key]
        results.append(score_candidate(profile, key=key, name=key, acronym=key.upper(), cfp_text=lt.text,
                                       publisher="ACM" if key == "icrds" else None, location=None, full_paper_due=due,
                                       venue_verified=True, questionable=False, now=now))
    ranked = [r.key for r in sorted(results, key=lambda r: -r.total)]
    gains = {k: v[2] for k, v in CORPUS.items()}
    p1 = precision_at_k(ranked, {"icrds", "wdp"}, 1)
    p2 = precision_at_k(ranked, {"icrds", "wdp"}, 2)
    ndcg = ndcg_at_k(ranked, gains, 4)
    out = REPO / "docs" / "evaluation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "m2_ranking_fixture_eval.json").write_text(json.dumps({
        "corpus": "synthetic fixture CFPs (fictional venues) - pilot baseline, not a production benchmark",
        "profile": PROFILE, "ranking": ranked, "precision@1": p1, "precision@2": p2, "ndcg@4": round(ndcg, 4),
        "components": {r.key: r.as_dict()["components"] for r in results}}, indent=2, default=str) + "\n")
    assert ranked[0] == "icrds" and ranked[-1] == "iccs"
    assert p1 == 1.0 and ndcg > 0.9
    wdp = next(r for r in results if r.key == "wdp")
    assert wdp.exclusion_reason and "passed" in wdp.exclusion_reason
    for r in results:
        assert {c.name for c in r.components} == {"topic_fit", "method_fit", "venue_confidence", "time_to_complete",
                                                  "deadline_slack", "cost"}
        assert next(c for c in r.components if c.name == "cost").score is None, "no budget -> unknown, not invented"


async def seed_registry(verified: bool = True):
    from rp_api.db.engine import session_scope
    from rp_api.db.models.cfp import VenueRegistryEntry

    async with session_scope("owner") as db:  # test cleanup only; the ingest role cannot delete reference rows
        await db.execute(delete(VenueRegistryEntry))
        await db.commit()
    async with session_scope("ingest") as db:
        for key, (_, host, _) in CORPUS.items():
            db.add(VenueRegistryEntry(series_key=key, name=key.upper(), acronym=key.upper(), homepage_url=f"https://{host}/",
                                      cfp_urls=[f"https://{host}/cfp"], publisher="ACM" if key == "icrds" else None,
                                      keywords=[], verification_status="verified" if verified else "unverified_seed",
                                      verified_by="test-operator"))
        db.add(VenueRegistryEntry(series_key="blocked", name="Blocked", homepage_url="https://blocked.example.org/",
                                  cfp_urls=["https://blocked.example.org/cfp"], verification_status="verified"))
        await db.commit()


def fake_web():
    pages = {f"{v[1]}": (FIX / v[0]).read_bytes() for v in CORPUS.values()}

    async def resolve(host, port):
        return ["10.9.9.9"] if host == "blocked.example.org" else ["93.184.216.34"]

    def handle(request: httpx.Request):
        host = request.headers["host"]
        if request.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/cfp" and host in pages:
            return httpx.Response(200, headers={"content-type": "text/html", "etag": f'"{host}-v1"'}, content=pages[host])
        return httpx.Response(404)

    return resolve, httpx.MockTransport(handle), pages


def workers(env):
    return [Worker(env.client, task_queue=q, workflows=WORKFLOWS[q], activities=ACTIVITIES[q]) for q in (QUEUE_RESEARCH, QUEUE_FETCH)]


async def wait_task(u, env, pid, kind, timeout=60):
    ws = workers(env)
    async with ws[0], ws[1]:
        await drain_outbox(env)
        for _ in range(timeout * 10):
            tasks = [t for t in (await u.get(f"/v1/projects/{pid}/tasks")).json()["items"] if t["kind"] == kind]
            if tasks and tasks[0]["state"] in ("succeeded", "failed_terminal"):
                return tasks[0]
            await asyncio.sleep(0.1)
    raise AssertionError(f"{kind} did not finish")


async def test_discovery_ranks_verified_official_sources(client, temporal_env, monkeypatch):
    import rp_research.features.discovery as disc
    from rp_research.fetch.fetcher import ControlledFetcher

    await seed_registry()
    resolve, transport, _ = fake_web()
    monkeypatch.setattr(disc, "fetcher", lambda: ControlledFetcher(resolver=resolve, transport=transport))
    u = await make_user(client)
    p = await make_project(u)
    r = await u.post(f"/v1/projects/{p['id']}/discovery")
    assert r.status_code == 422 and r.json()["error"]["code"] == "profile_incomplete"
    await client.put("/v1/research-profile", headers=u.h, json={**PROFILE, "project_id": p["id"]})
    r = await u.post(f"/v1/projects/{p['id']}/discovery")
    assert r.status_code == 202, r.text
    task = await wait_task(u, temporal_env, p["id"], "conference_discovery")
    assert task["state"] == "succeeded", task
    assert any("blocked" in f["reason"] for f in task["result"]["failures"]), "private-resolving source never fetched"
    cands = (await u.get(f"/v1/projects/{p['id']}/candidates")).json()["items"]
    assert cands[0]["acronym"] == "ICRDS" and cands[0]["components"]
    assert all(c["official_url"].endswith("/cfp") for c in cands)
    allc = (await u.get(f"/v1/projects/{p['id']}/candidates?include_excluded=true")).json()["items"]
    assert any(c["excluded"] or (c["exclusion_reason"] or "").find("passed") >= 0 for c in allc if c["acronym"] == "WDP")
    arts = (await u.get(f"/v1/projects/{p['id']}/artifacts?kind=source_snapshot")).json()["items"]
    assert len(arts) == 4, "every fetched source is a committed snapshot before ranking"

    # Importing a candidate runs the M1 official-source pipeline on its URL.
    import rp_research.features.cfp as cfp_feature

    monkeypatch.setattr(cfp_feature, "ControlledFetcher", lambda: ControlledFetcher(resolver=resolve, transport=transport))
    r = await u.post(f"/v1/projects/{p['id']}/candidates/{cands[0]['id']}/import")
    assert r.status_code == 202
    task = await wait_task(u, temporal_env, p["id"], "cfp_import")
    assert task["state"] == "succeeded", task
    cfp = (await u.get(f"/v1/projects/{p['id']}/cfp")).json()
    assert cfp["editions"][0]["edition"]["year"] == 2027


async def test_unverified_registry_blocks_discovery(client):
    await seed_registry(verified=False)
    from rp_api.db.engine import session_scope
    from rp_api.db.models.cfp import VenueRegistryEntry

    async with session_scope("owner") as db:
        await db.execute(delete(VenueRegistryEntry).where(VenueRegistryEntry.series_key == "blocked"))
        await db.commit()
    u = await make_user(client)
    p = await make_project(u)
    await client.put("/v1/research-profile", headers=u.h, json={**PROFILE, "project_id": p["id"]})
    r = await u.post(f"/v1/projects/{p['id']}/discovery")
    assert r.status_code == 422 and r.json()["error"]["code"] == "registry_empty"


async def test_registry_curation_requires_operator(client):
    u = await make_user(client)
    r = await u.client.put("/v1/registry", headers=u.h, json={"series_key": "xconf", "name": "X",
                                                              "homepage_url": "https://x.example.org/"})
    assert r.status_code == 403
    from rp_api.config import get_settings

    get_settings().platform_operators.append(u.email)
    try:
        r = await u.client.put("/v1/registry", headers=u.h, json={"series_key": "xconf", "name": "X",
                                                                  "homepage_url": "http://127.0.0.1/"})
        assert r.status_code == 422
        r = await u.client.put("/v1/registry", headers=u.h, json={
            "series_key": "xconf", "name": "X", "homepage_url": "https://x.example.org/",
            "questionable_evidence": [{"note": "listed as predatory"}]})
        assert r.status_code == 422 and r.json()["error"]["code"] == "evidence_required"
    finally:
        get_settings().platform_operators.remove(u.email)


async def test_monitor_not_modified_then_changed(client, temporal_env, monkeypatch):
    import rp_research.features.cfp as cfp_feature
    import rp_research.features.discovery as disc
    from rp_research.fetch.fetcher import ControlledFetcher

    pages = {"/cfp": (FIX / "icrds2027.html").read_bytes()}
    state = {"etag": '"v1"'}

    async def resolve(host, port):
        return ["93.184.216.34"]

    def handle(request):
        if request.headers.get("if-none-match") == state["etag"]:
            return httpx.Response(304)
        return httpx.Response(200, headers={"content-type": "text/html", "etag": state["etag"]}, content=pages["/cfp"])

    make = lambda: ControlledFetcher(resolver=resolve, transport=httpx.MockTransport(handle))  # noqa: E731
    monkeypatch.setattr(cfp_feature, "ControlledFetcher", make)
    monkeypatch.setattr(disc, "fetcher", make)
    u = await make_user(client)
    p = await make_project(u)
    await u.post("/v1/conferences/import", json={"project_id": p["id"], "url": "https://icrds2027.example.org/cfp"})
    await wait_task(u, temporal_env, p["id"], "cfp_import")
    ed = (await u.get(f"/v1/projects/{p['id']}/cfp")).json()["editions"][0]
    tr = next(t for t in ed["tracks"] if t["name"].startswith("Research"))
    await u.post(f"/v1/projects/{p['id']}/target", json={"edition_id": ed["edition"]["id"], "track_id": tr["id"],
                                                         "mode": "official", "official_source_confirmed": True,
                                                         "expected_version": 1})
    r = await u.post(f"/v1/projects/{p['id']}/cfp/check-now")
    assert r.status_code == 202, r.text
    task = await wait_task(u, temporal_env, p["id"], "cfp_monitor")
    assert task["result"]["outcome"] == "not_modified"
    state["etag"] = '"v2"'
    pages["/cfp"] = pages["/cfp"].replace(b"must not exceed 10 pages", b"must not exceed 9 pages")
    r = await u.post(f"/v1/projects/{p['id']}/cfp/check-now")
    task = await wait_task(u, temporal_env, p["id"], "cfp_monitor")
    assert task["result"]["outcome"] == "fetched" and "length.page_limit" in task["result"]["changed_rules"]
    hist = (await u.get(f"/v1/projects/{p['id']}/cfp/monitor")).json()["items"]
    assert [h["outcome"] for h in hist][:2] == ["changed", "not_modified"]
