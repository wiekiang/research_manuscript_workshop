"""M0.4 browser-slice backend and M1 acceptance:
create project -> import CFP (supplied document and controlled fetch) -> extract rules (deterministic + fixture
model + independent validation) -> ambiguous rules block advancement -> human resolution -> CFP gate persisted
with audit. Plus change detection: a changed rule reopens only the CFP gate; a deadline-only change does not."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from conftest import drain_outbox, make_project, make_user
from temporalio.worker import Worker

from rp_contracts.tasks import QUEUE_FETCH, QUEUE_RESEARCH
from rp_research.registry import ACTIVITIES, WORKFLOWS, load_features

pytestmark = pytest.mark.temporal
FIXTURE = Path(__file__).resolve().parents[2] / "services/research/src/rp_research/fixtures/cfp/icrds2027.html"
load_features()


def workers(env):
    return [Worker(env.client, task_queue=QUEUE_RESEARCH, workflows=WORKFLOWS[QUEUE_RESEARCH], activities=ACTIVITIES[QUEUE_RESEARCH]),
            Worker(env.client, task_queue=QUEUE_FETCH, workflows=WORKFLOWS[QUEUE_FETCH], activities=ACTIVITIES[QUEUE_FETCH])]


async def run_until_task_done(u, env, project_id, kind, timeout=60):
    ws = workers(env)
    async with ws[0], ws[1]:
        await drain_outbox(env)
        for _ in range(timeout * 10):
            tasks = (await u.get(f"/v1/projects/{project_id}/tasks")).json()["items"]
            mine = [t for t in tasks if t["kind"] == kind]
            if mine and mine[0]["state"] in ("succeeded", "failed_terminal", "cancelled"):
                return mine[0]
            await asyncio.sleep(0.1)
    raise AssertionError(f"task {kind} did not finish: {mine}")


async def supply_fixture(u, project_id):
    r = await u.post(f"/v1/projects/{project_id}/cfp/documents", files={"file": ("icrds2027.html", FIXTURE.read_bytes(), "text/html")},
                     data={"declared_origin_url": "https://icrds2027.example.org/cfp",
                           "origin_statement": "Saved from the organizer's official CFP page (fixture).",
                           "attest_official": "true"})
    assert r.status_code == 202, r.text
    return r.json()


def by_key(rules, key, track=None):
    return [r for r in rules if r["rule_key"] == key and (track is None or (r["track"] or "").startswith(track))]


async def test_supplied_cfp_journey_to_direction_review(client, temporal_env):
    u = await make_user(client)
    p = await make_project(u)
    await supply_fixture(u, p["id"])
    task = await run_until_task_done(u, temporal_env, p["id"], "cfp_extract_supplied")
    assert task["state"] == "succeeded", task
    assert task["result"]["passes"] == {"deterministic": "performed", "model_extraction": "performed",
                                        "independent_validation": "performed"}

    cfp = (await u.get(f"/v1/projects/{p['id']}/cfp")).json()
    ed = cfp["editions"][0]
    assert ed["edition"]["year"] == 2027 and {t["name"] for t in ed["tracks"]} >= {"Research Papers Track", "Short Papers Track"}
    rules = ed["rules"]
    # Every rule is source-linked with a verified locator, except the fabricated one.
    page = by_key(rules, "length.page_limit", "Research")[0]
    assert page["value"] == "10" and page["locator"]["section"].endswith("Research Papers Track") and page["status"] == "validated"
    fee = by_key(rules, "fees.statement")[0]
    assert fee["status"] == "needs_human_resolution" and any("quote not found" in x for x in fee["problems"])
    full = by_key(rules, "deadline.full_paper")[0]
    assert full["agreement"] == "conflict" and full["status"] == "needs_human_resolution"
    kinds = {d["deadline_kind"] for d in ed["deadlines"]}
    assert kinds >= {"abstract_registration", "full_paper", "rebuttal", "notification", "camera_ready", "author_registration"}
    abstract = next(d for d in ed["deadlines"] if d["deadline_kind"] == "abstract_registration")
    assert abstract["due_at"].startswith("2027-01-15T11:59"), "Jan 14 23:59 AoE == Jan 15 11:59 UTC"
    assert by_key(rules, "ai_policy.statement")[0]["status"] == "needs_human_resolution"

    # Target selection advances to TARGET_REVIEW; ambiguous rules then block the CFP gate.
    research = next(t for t in ed["tracks"] if t["name"].startswith("Research"))
    r = await u.post(f"/v1/projects/{p['id']}/target", json={"edition_id": ed["edition"]["id"], "track_id": research["id"],
                                                             "mode": "official", "official_source_confirmed": True,
                                                             "expected_version": 1})
    assert r.status_code == 200 and r.json()["state"] == "TARGET_REVIEW", r.text
    decl = cfp["declaration"]["text"]
    r = await u.post(f"/v1/projects/{p['id']}/cfp/confirm", json={"declaration_accepted": True, "declaration_text": decl})
    assert r.status_code == 422 and len(r.json()["error"]["details"]["reasons"]) >= 5

    cfp = (await u.get(f"/v1/projects/{p['id']}/cfp")).json()
    open_items = [x for x in cfp["editions"][0]["rules"] if x["status"] == "needs_human_resolution"]
    for item in open_items:
        if item["rule_key"] == "fees.statement":
            body = {"action": "reject", "rationale": "Not stated in the official CFP."}
        elif item["rule_key"] == "deadline.full_paper":
            body = {"action": "edit", "date": "2027-01-21", "timezone": "AoE", "rationale": "Source says January 21 AoE."}
        elif item["item_type"] == "deadline":
            body = {"action": "confirm", "timezone": "UTC-12", "time": "23:59",
                    "rationale": "Organizers confirmed by email that all deadlines are AoE."}
        else:
            body = {"action": "confirm", "rationale": "Read the official text; disclosure goes in acknowledgments."}
        r = await u.post(f"/v1/projects/{p['id']}/cfp/resolve", json={"rule_id": item["id"], **body})
        assert r.status_code == 200, (item["rule_key"], r.text)
    r = await u.post(f"/v1/projects/{p['id']}/cfp/confirm", json={"declaration_accepted": True, "declaration_text": decl})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "DIRECTION_REVIEW"
    proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    assert proj["state"] == "DIRECTION_REVIEW" and any(a["gate"] == "CFP" and a["status"] == "valid" for a in proj["approvals"])
    events = [e["type"] for e in (await u.get(f"/v1/projects/{p['id']}/events")).json()["items"]]
    assert events.count("state.changed") == 2
    full_dl = next(d for d in (await u.get(f"/v1/projects/{p['id']}/cfp")).json()["editions"][0]["deadlines"]
                   if d["deadline_kind"] == "full_paper")
    assert full_dl["stated_date"] == "2027-01-21"


def fake_web(pages: dict[str, bytes]):
    async def resolve(host, port):
        return ["93.184.216.34"]

    def handle(request: httpx.Request):
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8", "etag": '"v1"'}, content=body)

    return resolve, httpx.MockTransport(handle)


async def test_controlled_fetch_import_and_change_detection(client, temporal_env, monkeypatch):
    import rp_research.features.cfp as cfp_feature
    from rp_research.fetch.fetcher import ControlledFetcher

    pages = {"/cfp": FIXTURE.read_bytes()}
    resolve, transport = fake_web(pages)
    monkeypatch.setattr(cfp_feature, "ControlledFetcher", lambda: ControlledFetcher(resolver=resolve, transport=transport))
    u = await make_user(client)
    p = await make_project(u)
    r = await u.post("/v1/conferences/import", json={"project_id": p["id"], "url": "https://icrds2027.example.org/cfp"})
    assert r.status_code == 202, r.text
    task = await run_until_task_done(u, temporal_env, p["id"], "cfp_import")
    assert task["state"] == "succeeded", task
    cfp = (await u.get(f"/v1/projects/{p['id']}/cfp")).json()
    snap = cfp["editions"][0]["snapshots"][0]
    assert snap["origin"] == "fetched" and snap["hops"][0]["ip"] == "93.184.216.34"
    assert "script" in " ".join(snap["scan_report"]["flags"])

    # Fast path through the gate.
    ed = cfp["editions"][0]
    track = next(t for t in ed["tracks"] if t["name"].startswith("Research"))
    await u.post(f"/v1/projects/{p['id']}/target", json={"edition_id": ed["edition"]["id"], "track_id": track["id"],
                                                         "mode": "official", "official_source_confirmed": True,
                                                         "expected_version": 1})
    for item in [x for x in (await u.get(f"/v1/projects/{p['id']}/cfp")).json()["editions"][0]["rules"]
                 if x["status"] == "needs_human_resolution"]:
        body = ({"action": "reject"} if item["rule_key"] == "fees.statement" else
                {"action": "edit", "date": "2027-01-21", "timezone": "AoE"} if item["rule_key"] == "deadline.full_paper" else
                {"action": "confirm", "timezone": "AoE"} if item["item_type"] == "deadline" else {"action": "confirm"})
        await u.post(f"/v1/projects/{p['id']}/cfp/resolve", json={"rule_id": item["id"], "rationale": "checked source", **body})
    r = await u.post(f"/v1/projects/{p['id']}/cfp/confirm", json={"declaration_accepted": True,
                                                                   "declaration_text": cfp["declaration"]["text"]})
    assert r.status_code == 200 and r.json()["state"] == "DIRECTION_REVIEW", r.text

    # 1) Deadline-only change: schedule goes stale, the CFP confirmation and state are untouched.
    pages["/cfp"] = FIXTURE.read_bytes().replace(b"Camera-ready deadline: April 15, 2027", b"Camera-ready deadline: April 22, 2027")
    await u.post("/v1/conferences/import", json={"project_id": p["id"], "url": "https://icrds2027.example.org/cfp"},
                 headers={"Idempotency-Key": "reimport-1"})
    task = await run_until_task_done(u, temporal_env, p["id"], "cfp_import")
    assert task["state"] == "succeeded", task
    proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    assert proj["state"] == "DIRECTION_REVIEW"
    assert any(a["gate"] == "CFP" and a["status"] == "valid" for a in proj["approvals"])
    sched = [a for a in (await u.get(f"/v1/projects/{p['id']}/artifacts?kind=deadline_schedule")).json()["items"]]
    assert sched and sched[0]["freshness"] == "stale"

    # 2) A material rule change (page limit) invalidates the CFP confirmation and reopens TARGET_REVIEW only.
    pages["/cfp"] = pages["/cfp"].replace(b"must not exceed 10 pages", b"must not exceed 8 pages")
    await u.post("/v1/conferences/import", json={"project_id": p["id"], "url": "https://icrds2027.example.org/cfp"},
                 headers={"Idempotency-Key": "reimport-2"})
    task = await run_until_task_done(u, temporal_env, p["id"], "cfp_import")
    assert task["state"] == "succeeded", task
    assert task["result"]["passes"]["model_extraction"].startswith("not_performed"), "no recording for the edited page"
    proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    assert proj["state"] == "TARGET_REVIEW"
    cfp_appr = [a for a in proj["approvals"] if a["gate"] == "CFP"]
    assert cfp_appr[0]["status"] == "invalidated" and "page_limit" in cfp_appr[0]["invalidation_reason"]
    rules = (await u.get(f"/v1/projects/{p['id']}/cfp")).json()["editions"][0]["rules"]
    page = by_key(rules, "length.page_limit", "Research")[0]
    assert page["value"] == "8" and page["change_kind"] == "changed" and page["status"] == "needs_human_resolution"
    notes = [n for n in (await u.get("/v1/notifications")).json()["items"] if n["type"] == "rule.changed"]
    assert notes
