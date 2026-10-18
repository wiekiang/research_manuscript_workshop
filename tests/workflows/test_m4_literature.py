"""M4 acceptance: no-fee search (OpenAIRE + Crossref) with recorded responses, DOI identity verification (a
fabricated DOI is blocked), global rights-cleared metadata shared across tenants without leaking private records,
evidence extraction with verbatim-quote verification, policy-based claim verification incl. a stricter policy
upgrade, coverage that reconciles to stored records, and advisory opportunities with H1 still incomplete."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from conftest import drain_outbox, make_project, make_user
from temporalio.worker import Worker

from rp_contracts.tasks import QUEUE_FETCH, QUEUE_RESEARCH
from rp_research.adapters import base as adapter_base
from rp_research.registry import ACTIVITIES, WORKFLOWS, load_features

pytestmark = pytest.mark.temporal
ROOT = Path(__file__).resolve().parents[2]
PFIX = ROOT / "services/research/tests/fixtures/providers"
PAPER = ROOT / "services/research/src/rp_research/fixtures/papers/provenance-pipelines.txt"
KNOWN_DOI = "10.14778/3415478.3415556"
FAKE_DOI = "10.9999/fabricated.doi.2025.00001"
load_features()

CR_SEARCH = json.loads((PFIX / "crossref_search.json").read_text())
CR_ITEMS = {i["DOI"].lower(): i for i in CR_SEARCH["message"]["items"]}


def provider_web(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "api.openaire.eu" in url:
        if "pid=" in url:
            if KNOWN_DOI in url:
                return httpx.Response(200, json=json.loads((PFIX / "openaire_pid.json").read_text()))
            return httpx.Response(200, json={"header": {"numFound": 0, "page": 1, "pageSize": 5}, "results": []})
        return httpx.Response(200, json=json.loads((PFIX / "openaire_search.json").read_text()))
    if "api.crossref.org/works/" in url:
        doi = url.split("/works/", 1)[1].split("?")[0].lower()
        if doi == KNOWN_DOI:
            return httpx.Response(200, json=json.loads((PFIX / "crossref_work.json").read_text()))
        if doi in CR_ITEMS:
            return httpx.Response(200, json={"message": CR_ITEMS[doi]})
        return httpx.Response(404, text="Resource not found.")
    if "api.crossref.org/works" in url:
        return httpx.Response(200, json=CR_SEARCH)
    if "api.datacite.org/dois/" in url:
        if "10.48550/arxiv.2006.12117" in url:
            return httpx.Response(200, json=json.loads((PFIX / "datacite_work.json").read_text()))
        return httpx.Response(404, json={"errors": [{"status": "404"}]})
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def providers():
    adapter_base.use_transport(httpx.MockTransport(provider_web))
    yield
    adapter_base.use_transport(None)


def workers(env):
    return [Worker(env.client, task_queue=q, workflows=WORKFLOWS[q], activities=ACTIVITIES[q]) for q in (QUEUE_RESEARCH, QUEUE_FETCH)]


async def run_all(u, env, pid, timeout=120):
    """Run workers until no task of the project is queued/running."""
    ws = workers(env)
    async with ws[0], ws[1]:
        for _ in range(timeout * 10):
            await drain_outbox(env)
            tasks = (await u.get(f"/v1/projects/{pid}/tasks")).json()["items"]
            if tasks and all(t["state"] in ("succeeded", "failed_terminal", "cancelled") for t in tasks):
                return tasks
            await asyncio.sleep(0.1)
    raise AssertionError([(t["kind"], t["state"]) for t in tasks])


async def search(u, pid, providers=("openaire", "crossref")):
    r = await u.post(f"/v1/projects/{pid}/searches", json={"query": "provenance reproducibility data pipelines",
                                                           "providers": list(providers), "max_results": 5})
    assert r.status_code == 202, r.text
    return r.json()


async def test_search_identity_and_cross_tenant_sharing(client, temporal_env):
    a = await make_user(client)
    pa = await make_project(a)
    res = await search(a, pa["id"])
    assert res["refused"] == []
    r = await a.post(f"/v1/projects/{pa['id']}/searches", json={"query": "x y z", "providers": ["elicit"]})
    assert r.status_code == 422, "blocked providers are refused, never used"
    tasks = await run_all(a, temporal_env, pa["id"])
    assert all(t["state"] == "succeeded" for t in tasks), tasks
    papers = (await a.get(f"/v1/projects/{pa['id']}/papers")).json()["items"]
    dois = [p["doi"] for p in papers if p["doi"]]
    assert len(dois) == len(set(dois)), "deduplicated by DOI"
    known = next(p for p in papers if p["doi"] == KNOWN_DOI)
    assert set(known["sources"]) == {"openaire", "crossref"} and known["identity_status"] == "verified"
    assert known["global_paper_id"]
    # Non-Crossref DOIs (arXiv/Zenodo) are verified against DataCite instead of being flagged as fabricated.
    r = await a.post(f"/v1/projects/{pa['id']}/papers", json={
        "doi": "10.48550/arXiv.2006.12117", "year": 2020,
        "title": "Machine Learning Pipelines: Provenance, Reproducibility and FAIR Data Principles"})
    arxiv_id = r.json()["id"]

    # A fabricated DOI entered manually is not verified and cannot support a verified claim.
    r = await a.post(f"/v1/projects/{pa['id']}/papers", json={"doi": FAKE_DOI, "title": "A Paper That Does Not Exist", "year": 2025})
    fake_id = r.json()["id"]
    await a.patch(f"/v1/projects/{pa['id']}/papers/{known['id']}", json={"notes": "tenant A private note"})
    await run_all(a, temporal_env, pa["id"])
    listing = {p["id"]: p for p in (await a.get(f"/v1/projects/{pa['id']}/papers")).json()["items"]}
    assert listing[arxiv_id]["identity_status"] == "verified"
    assert listing[arxiv_id]["identity_verification"]["source"] == "datacite"
    fake = listing[fake_id]
    assert fake["identity_status"] == "not_found"
    claim = (await a.post(f"/v1/projects/{pa['id']}/claims", json={"proposition": "A fabricated source states X.",
                                                                   "category": "descriptive"})).json()
    await a.post(f"/v1/claims/{claim['id']}/support", json={"paper_id": fake_id})
    c = (await a.post(f"/v1/claims/{claim['id']}/verify", json={"human_support": True, "human_support_note": "I read it"})).json()["claim"]
    assert c["status"] != "verified" and "identity_deterministic" in c["decision"]["outstanding"]

    # Tenant B reuses the same global metadata record but sees none of tenant A's private data.
    b = await make_user(client)
    pb = await make_project(b)
    await search(b, pb["id"], providers=("crossref",))
    await run_all(b, temporal_env, pb["id"])
    bk = next(p for p in (await b.get(f"/v1/projects/{pb['id']}/papers")).json()["items"] if p["doi"] == KNOWN_DOI)
    assert bk["global_paper_id"] == known["global_paper_id"]
    assert bk["notes"] is None
    assert (await b.get(f"/v1/projects/{pa['id']}/papers")).status_code == 404
    assert (await b.get(f"/v1/projects/{pa['id']}/evidence")).status_code == 404
    from sqlalchemy import text

    from rp_api.db.engine import session_scope

    async with session_scope("app") as db:
        cols = (await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='global_papers'"))).scalars().all()
    assert "abstract" not in cols and "notes" not in cols and "embedding" not in cols


async def upload_known_paper(u, pid):
    r = await u.post(f"/v1/projects/{pid}/papers/upload",
                     files={"file": ("pipelines.txt", PAPER.read_bytes(), "text/plain")},
                     data={"doi": KNOWN_DOI, "title": "Improving reproducibility of data science pipelines",
                           "rights_statement": "Author-provided fixture excerpt licensed for this test.", "attest_rights": "true"})
    assert r.status_code == 202, r.text
    return r.json()["paper"]["id"]


async def test_evidence_claims_policy_upgrade_and_coverage(client, temporal_env):
    u = await make_user(client)
    p = await make_project(u)
    await upload_known_paper(u, p["id"])
    tasks = await run_all(u, temporal_env, p["id"])
    assert all(t["state"] == "succeeded" for t in tasks), tasks
    ev = (await u.get(f"/v1/projects/{p['id']}/evidence")).json()
    assert len(ev["passages"]) == 3, "the fabricated quote was dropped"
    assert all(x["verified_in_source"] and x["extraction_method"] == "model_assisted" for x in ev["passages"])
    claims = {c["proposition"]: c for c in ev["claims"]}
    assert "All pipelines became fully reproducible." not in claims, "claim whose only passage was fabricated is not registered"
    claim = next(c for c in ev["claims"] if c["category"] == "descriptive")
    assert claim["status"] == "unverified" and "support_assessed" in claim["decision"]["outstanding"]

    # Model-assisted support assessment satisfies the descriptive minimum under policy v1 (labelled as such).
    r = await u.post(f"/v1/claims/{claim['id']}/verify", json={"request_model_assessment": True})
    assert r.status_code == 200
    await run_all(u, temporal_env, p["id"])
    c = next(x for x in (await u.get(f"/v1/projects/{p['id']}/evidence")).json()["claims"] if x["id"] == claim["id"])
    assert c["status"] == "verified" and c["gate_eligible"], (c["decision"], c["verifications"],
                                                             [t["result"] for t in (await u.get(f"/v1/projects/{p['id']}/tasks")).json()["items"]][:2])
    sup = [v for v in c["verifications"] if v["check"] == "support"]
    assert sup and sup[-1]["method"] == "model_assisted" and sup[-1]["evidence"]["label"].startswith("fixture")

    # Novelty/causal claims can never be verified by a model alone.
    nov = (await u.post(f"/v1/projects/{p['id']}/claims", json={"proposition": "This is the first study of version drift.",
                                                                "category": "novelty"})).json()
    assert nov["critical"] and "human_judgment" in nov["decision"]["outstanding"]

    # A stricter policy (descriptive now needs a human) preserves history but removes gate eligibility.
    from rp_api.config import get_settings

    get_settings().platform_operators.append(u.email)
    try:
        pol = (await u.get("/v1/verification-policies")).json()["items"][-1]["rules"]
        for rule in pol["rules"]:
            if rule["category"] == "descriptive":
                rule["requires"] = rule["requires"] + ["support_human"]
        pol["version"] = f"claim-policy-test-{p['id'][:8]}"
        r = await u.post("/v1/verification-policies", json=pol)
        assert r.status_code == 201, r.text
        r = await u.post(f"/v1/projects/{p['id']}/claims/reassess")
        assert r.json()["reopened"] >= 1
        c = next(x for x in (await u.get(f"/v1/projects/{p['id']}/evidence")).json()["claims"] if x["id"] == claim["id"])
        assert c["status"] == "unverified" and not c["gate_eligible"] and "support_human" in c["decision"]["outstanding"]
        assert any(d["state"] == "superseded" and d["status"] == "verified" for d in c["decisions"]), "old decision kept"
        c = (await u.post(f"/v1/claims/{claim['id']}/verify", json={"human_support": True,
                                                                    "human_support_note": "Checked the Results passage."})).json()["claim"]
        assert c["status"] == "verified" and c["decision"]["policy_version"] == pol["version"]
    finally:
        get_settings().platform_operators.remove(u.email)
        from sqlalchemy import update

        from rp_api.db.engine import session_scope
        from rp_api.db.models.literature import VerificationPolicyRecord

        async with session_scope("owner") as db:
            await db.execute(update(VerificationPolicyRecord).values(active=False))
            await db.execute(update(VerificationPolicyRecord).where(VerificationPolicyRecord.version == "claim-policy-1")
                             .values(active=True))
            await db.commit()

    # Licence-blocked full text: open access without a reuse licence is not stored.
    await search(u, p["id"], providers=("openaire",))
    await run_all(u, temporal_env, p["id"])
    oa = next(x for x in (await u.get(f"/v1/projects/{p['id']}/papers")).json()["items"]
              if x["doi"] == "10.1007/978-3-030-67681-0_3")  # licence "Springer TDM": no recorded reuse rights
    assert oa["rights"]["storage_permitted"] is False
    await u.post(f"/v1/projects/{p['id']}/papers/{oa['id']}/fulltext")
    await run_all(u, temporal_env, p["id"])
    oa = next(x for x in (await u.get(f"/v1/projects/{p['id']}/papers")).json()["items"] if x["id"] == oa["id"])
    assert oa["fulltext_status"] in ("not_permitted", "inaccessible") and not oa["fulltext_artifact_id"]

    # Screening + coverage reconcile to stored records and never claim comprehensiveness.
    await u.post(f"/v1/projects/{p['id']}/papers/{oa['id']}/screen", json={"stage": "title_abstract", "decision": "exclude",
                                                                           "reason": "not about pipelines"})
    cov = (await u.get(f"/v1/projects/{p['id']}/literature-coverage")).json()
    papers = (await u.get(f"/v1/projects/{p['id']}/papers")).json()["items"]
    searches = (await u.get(f"/v1/projects/{p['id']}/searches")).json()["items"]
    k = cov["counts"]
    assert k["retrieved_records"] == sum(s["retrieved_count"] for s in searches)
    assert k["papers_total"] == len(papers) and k["fulltext_reviewed"] == sum(1 for x in papers if x["fulltext_status"] == "parsed")
    assert k["excluded"] == 1 and "not about pipelines" in k["exclusion_reasons"]
    assert k["papers_contributing_verified_evidence"] == 1
    assert "comprehensive" not in cov["coverage_level"] and "may miss relevant work" in cov["message"]
    again = (await u.get(f"/v1/projects/{p['id']}/literature-coverage")).json()
    assert again["version"] == cov["version"], "unchanged inputs do not create a new version"


async def test_opportunities_are_advisory_and_h1_stays_incomplete(client, temporal_env, monkeypatch):
    from rp_api.services import gates

    async def ok(db, project, gid=None):
        return gates.GateResult("x", True)

    monkeypatch.setitem(gates._REGISTRY, "target.selected", ok)
    monkeypatch.setitem(gates._REGISTRY, "cfp.confirmed", ok)
    u = await make_user(client)
    r = await u.post("/v1/projects", json={"title": "Version drift study", "topic": "reproducibility of data pipelines",
                                           "responsibility_acknowledged": True})
    p = r.json()
    assert (await u.post(f"/v1/projects/{p['id']}/opportunities/generate")).status_code == 422
    await search(u, p["id"], providers=("crossref",))
    await run_all(u, temporal_env, p["id"])
    r = await u.post(f"/v1/projects/{p['id']}/opportunities/generate")
    assert r.status_code == 202
    tasks = await run_all(u, temporal_env, p["id"])
    opp_task = next(t for t in tasks if t["kind"] == "opportunity_generation")
    assert opp_task["state"] == "succeeded" and opp_task["result"]["at_least_two"], opp_task
    assert any("removed references" in x for x in opp_task["result"]["agent_problems"]), "fabricated ids were stripped"
    ops = (await u.get(f"/v1/projects/{p['id']}/opportunities")).json()
    assert len(ops["items"]) >= 2 and ops["direction_state"] == "direction_proposed"
    first = ops["items"][0]
    assert first["closest_work"], "nearest prior work falls back to similarity over project papers"
    assert first["novelty_caveat"] and first["rationale"]["label"].startswith("Proposed contribution")
    assert first["rationale"]["gap_evidence"] == [], "fabricated gap evidence id was not kept"
    st = {s["study_type"]: s for s in first["study_types"]}
    # Systematic review became submission-capable in M10 (systematic_review@2); recommendations follow the registry.
    assert st["systematic_review"]["method_enabled"] is True
    assert not any("planning only" in b for b in st["systematic_review"]["blockers"])
    assert first["feasibility"]["status"] in ("feasible", "at_risk", "infeasible") and first["feasibility"]["uncertainty"]

    # Researcher edits the rationale: new version + ledger entry; the agent draft is retained.
    rid = first["rationale"]["id"]
    r = await u.patch(f"/v1/projects/{p['id']}/rationales/{rid}", json={"gap": "Only Python pipelines have been studied (my reading)."})
    assert r.json()["version"] == 2 and r.json()["status"] == "researcher_edited"
    led = (await u.get(f"/v1/projects/{p['id']}/contribution-ledger")).json()["items"]
    assert any(e["source_action"] == "rationale.edit" for e in led)

    # H1 cannot be completed in M4: advancing past DIRECTION_REVIEW is refused.
    proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    for target in ("TARGET_REVIEW", "DIRECTION_REVIEW"):
        r = await u.post(f"/v1/projects/{p['id']}/advance", json={"requested_state": target, "expected_version": proj["version"]})
        assert r.status_code == 200, r.text
        proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    assert (await u.get(f"/v1/projects/{p['id']}/opportunities")).json()["direction_state"] == "awaiting_H1"
    r = await u.post(f"/v1/projects/{p['id']}/advance", json={"requested_state": "PROTOCOL_REVIEW", "expected_version": proj["version"]})
    assert r.status_code == 422 and any(g["gate_id"] == "h1.approved" and not g["passed"] for g in r.json()["error"]["details"]["gates"])

