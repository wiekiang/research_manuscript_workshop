"""M5 acceptance: M4 proposals require a substantive H1; the selected method drives distinct stages; H2 freezes a
reviewed protocol hash and results bind to it; supplied outcomes keep honest assurance labels; the contribution
matrix and gap assessment cannot overstate; H3 advances to drafting; a method switch never carries H2/H3; a disabled
method stays planning-only."""

from __future__ import annotations

import pytest
from conftest import make_user
from test_m4_literature import providers, run_all, search  # noqa: F401  (autouse provider fixture)

from rp_research.fixtures import m5_protocol as fx

pytestmark = pytest.mark.temporal
PRED = b"y_true,y_pred\n1,1\n0,0\n1,1\n0,1\n1,1\n0,0\n1,0\n0,0\n"


@pytest.fixture
def open_cfp(monkeypatch):
    from rp_api.services import gates

    async def ok(db, project):
        return gates.GateResult("x", True)

    monkeypatch.setitem(gates._REGISTRY, "target.selected", ok)
    monkeypatch.setitem(gates._REGISTRY, "cfp.confirmed", ok)


async def project_at_direction_review(client, env):
    u = await make_user(client)
    p = (await u.post("/v1/projects", json={"title": "Version drift in R", "topic": "reproducibility of data pipelines",
                                            "responsibility_acknowledged": True})).json()
    await search(u, p["id"], providers=("crossref",))
    await run_all(u, env, p["id"])
    await u.post(f"/v1/projects/{p['id']}/opportunities/generate")
    await run_all(u, env, p["id"])
    proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    for target in ("TARGET_REVIEW", "DIRECTION_REVIEW"):
        r = await u.post(f"/v1/projects/{p['id']}/advance", json={"requested_state": target, "expected_version": proj["version"]})
        assert r.status_code == 200, r.text
        proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    opp = (await u.get(f"/v1/projects/{p['id']}/opportunities")).json()["items"][0]
    return u, p["id"], opp


async def decl(u, pid, gate):
    return (await u.get(f"/v1/projects/{pid}/approvals")).json()["declarations"][gate]["text"]


async def h1(u, pid, opp, **over):
    body = {"opportunity_id": opp["id"], "research_question": opp["research_question"] + " (scoped to R pipelines)",
            "intended_contribution": "Evidence on version recording beyond Python.",
            "how_it_differs": "Prior work only measured Python pipelines; I test R where package management differs.",
            "method_rationale": "Restoration outcomes are directly measurable re-execution results.",
            "rationale_approved": True, "feasibility_rationale": "No deadline recorded yet; I accept the schedule risk.",
            "declaration_accepted": True, "declaration_text": await decl(u, pid, "H1")}
    body.update(over)
    return await u.post(f"/v1/projects/{pid}/direction/approve", json=body)


async def select(u, pid, study_type, opp=None, rationale="The track's accepted categories are not listed in the CFP."):
    return await u.post(f"/v1/projects/{pid}/study-type/select", json={
        "study_type": study_type, "venue_category": "full_paper", "opportunity_id": opp["id"] if opp else None,
        "rationale": rationale})


async def frozen_protocol(u, pid, env, review="model"):
    r = await u.post(f"/v1/projects/{pid}/protocols", json={"sections": fx.SECTIONS, "ethics_rights": fx.ETHICS,
                                                           "compute_estimate": fx.COMPUTE, "cost_estimate_cents": fx.COST_CENTS})
    assert r.status_code == 201, r.text
    prot = r.json()
    assert prot["validation"]["missing_sections"] == []
    d2 = await decl(u, pid, "H2")
    r = await u.post(f"/v1/projects/{pid}/protocols/1/approve", json={"declaration_accepted": True, "declaration_text": d2})
    assert r.status_code == 422 and r.json()["error"]["details"]["review"], "independent review (or waiver) required"
    if review == "model":
        await u.post(f"/v1/projects/{pid}/protocols/1/review")
        await run_all(u, env, pid)
        prot = (await u.get(f"/v1/projects/{pid}/protocols")).json()["items"][0]
        assert prot["review_status"] == "performed" and any(i["severity"] == "blocker" for i in prot["review_issues"])
        r = await u.post(f"/v1/projects/{pid}/protocols/1/approve", json={"declaration_accepted": True, "declaration_text": d2})
        assert r.status_code == 422 and r.json()["error"]["details"]["unresolved_blocker_issues"]
        idx = next(i for i, x in enumerate(prot["review_issues"]) if x["severity"] == "blocker")
        await u.post(f"/v1/projects/{pid}/protocols/1/issues/resolve", json={
            "index": idx, "resolution": "fixed", "note": "Reframed as exploratory with interval reporting."})
    else:
        await u.post(f"/v1/projects/{pid}/protocols/1/waive-review", json={
            "rationale": "No model provider is configured; reviewed by a colleague offline instead."})
    r = await u.post(f"/v1/projects/{pid}/protocols/1/approve", json={"declaration_accepted": True, "declaration_text": d2})
    assert r.status_code == 200, r.text
    return r.json()


async def contribute(u, pid, name, data, ctype="results"):
    r = await u.post(f"/v1/projects/{pid}/contributions", files={"file": (name, data, "text/csv")},
                     data={"contribution_type": ctype, "title": name, "pii_classification": "none",
                           "rights_statement": "Produced by me from public pipelines.", "visibility": "private"})
    assert r.status_code == 201, r.text
    return r.json()


def manifest(prot, metrics, files, **kw):
    return {"title": kw.pop("title", "Restoration classifier accuracy"), "protocol_version": prot["protocol"]["version"],
            "protocol_hash": prot["frozen_hash"], "data_origin": "eight public R pipelines",
            "data_rights": "public source code under MIT/GPL", "methods": "re-executed each pipeline; manual labels",
            "metrics": metrics, "sample_size": 8, "limitations": "small non-random sample", "files": files,
            "attestation_accepted": True, **kw}


async def test_empirical_path_through_h1_h2_results_and_h3(client, temporal_env, open_cfp):
    u, pid, opp = await project_at_direction_review(client, temporal_env)
    r = await h1(u, pid, opp)
    assert r.status_code == 422 and "select a study type" in str(r.json())
    r = await select(u, pid, "empirical_quantitative", opp, rationale=None)
    assert r.status_code == 422 and r.json()["error"]["code"] == "rationale_required"
    assert (await select(u, pid, "empirical_quantitative", opp)).status_code == 201
    r = await h1(u, pid, opp, rationale_approved=False, how_it_differs="it is new")
    reasons = r.json()["error"]["details"]["reasons"]
    assert r.status_code == 422 and any("Paper Rationale" in x for x in reasons) and any("own words" in x for x in reasons)
    r = await h1(u, pid, opp)
    assert r.status_code == 200, r.text
    assert r.json()["transition"]["state"] == "PROTOCOL_REVIEW"
    led = (await u.get(f"/v1/projects/{pid}/contribution-ledger")).json()["items"]
    assert any(e["source_action"] == "direction.approve" for e in led)

    prot = await frozen_protocol(u, pid, temporal_env, review="model")
    assert prot["transition"]["state"] == "RESEARCH_ACTIVE" and len(prot["frozen_hash"]) == 64
    wf = (await u.get(f"/v1/projects/{pid}/workflow-definition")).json()
    assert [s["id"] for s in wf["stages"]] == ["data_provenance", "analysis", "result_checks"]

    preds = await contribute(u, pid, "predictions.csv", PRED)
    raw = await contribute(u, pid, "labels.csv", b"pipeline,restored\nA,1\n", ctype="dataset")
    files = [{"role": "predictions", "artifact_id": preds["artifact_id"]}, {"role": "raw_data", "artifact_id": raw["artifact_id"]}]
    acc = [{"name": "accuracy", "value": 0.75, "unit": "proportion", "n": 8, "numerator": 6, "denominator": 8}]
    bad = manifest(prot, acc, files)
    bad["protocol_hash"] = "0" * 64
    assert (await u.post(f"/v1/projects/{pid}/results", json=bad)).status_code == 422, "results bind to the frozen hash"
    r1 = (await u.post(f"/v1/projects/{pid}/results", json=manifest(prot, acc, files))).json()
    r2 = (await u.post(f"/v1/projects/{pid}/results", json=manifest(
        prot, [{"name": "proportion", "value": 0.5, "unit": "proportion"}], [], title="Restoration rate (aggregate only)"))).json()
    await run_all(u, temporal_env, pid)
    res = {x["result_key"]: x for x in (await u.get(f"/v1/projects/{pid}/results")).json()["items"]}
    assert res[r1["result_key"]]["assurance_level"] == "independently_checked"
    agg = res[r2["result_key"]]
    assert agg["assurance_level"] == "declared", "aggregate without raw outputs is never independently checked"
    assert "raw predictions/outputs" in agg["assessment"]["missing"]
    assert "do not describe them as independently checked" in agg["assessment"]["wording_limits"][0]

    s = await u.post(f"/v1/projects/{pid}/method-stages/result_checks", json={"description": "x"})
    assert s.status_code == 422, "predecessor stages are enforced"
    s = await u.post(f"/v1/projects/{pid}/method-stages/data_provenance", json={"description": "", "fields": {
        "data_origin": "eight public R pipelines from CRAN task views", "selection_criteria": "public inputs, no credentials",
        "pii_classification": "none", "rights": "MIT/GPL"}, "contribution_ids": [raw["id"]]})
    assert s.json()["status"] == "validated", s.json()
    s = await u.post(f"/v1/projects/{pid}/method-stages/analysis", json={"description": "", "result_ids": []})
    assert s.json()["status"] == "failed", "prose alone cannot complete a stage that needs results"
    s = await u.post(f"/v1/projects/{pid}/method-stages/analysis", json={"description": "", "result_ids": [r1["id"], r2["id"]]})
    assert s.json()["status"] == "validated"
    s = await u.post(f"/v1/projects/{pid}/method-stages/result_checks", json={"description": "", "result_ids": [r1["id"], r2["id"]]})
    assert s.json()["status"] == "validated" and s.json()["transition"]["state"] == "OUTCOME_REVIEW"

    c = (await u.post(f"/v1/projects/{pid}/results/{r1['id']}/claims", json={
        "proposition": "The restoration classifier reached 0.75 accuracy (6/8) on the eight pipelines.",
        "metric_name": "accuracy", "researcher_confirms_match": True})).json()
    assert c["status"] == "verified" and c["assurance_level"] == "independently_checked"
    assert "recomputed from the supplied raw outputs" in c["wording_limits"][0]
    d3 = await decl(u, pid, "H3")
    r = await u.post(f"/v1/projects/{pid}/results/approve", json={"interpretation": "x" * 50, "limitations": "y" * 30,
                                                                 "anomalies_reviewed": True, "declaration_accepted": True,
                                                                 "declaration_text": d3})
    assert r.status_code == 422 and any("matrix" in x for x in r.json()["error"]["details"]["reasons"])
    matrix = (await u.get(f"/v1/projects/{pid}/contribution-matrix")).json()["items"]
    assert matrix[0]["origin"] == "draft" and r1["result_key"] in matrix[0]["evidence_ids"]
    row = {k: matrix[0][k] for k in ("rq_index", "research_question", "intended_novelty", "intended_contribution",
                                     "success_criterion")}
    r = await u.post(f"/v1/projects/{pid}/contribution-matrix/review", json={"rows": [{
        **row, "evidence_ids": [r1["result_key"], c["claim_key"]], "outcome": "partially_supported",
        "validity_assessment": "Small sample; supports restoration for most but not all pipelines.",
        "limitations": "n=8", "h3_decision": "accepted"}]})
    assert r.status_code == 200, r.text
    r = await u.post(f"/v1/projects/{pid}/gap-resolution", json={"status": "addressed", "explanation": "All solved." * 3})
    assert r.status_code == 422 and r.json()["error"]["code"] == "overstated"
    r = await u.post(f"/v1/projects/{pid}/gap-resolution", json={"status": "partially_addressed", "supporting_ids": [c["claim_key"]],
                                                                 "explanation": "Only R and a small sample were studied."})
    assert r.status_code == 200
    r = await u.post(f"/v1/projects/{pid}/results/approve", json={
        "interpretation": "Version records restored most affected R pipelines in this small exploratory sample.",
        "limitations": "Eight pipelines; exploratory framing; declared aggregate not independently checked.",
        "anomalies_reviewed": True, "declaration_accepted": True, "declaration_text": d3})
    assert r.status_code == 200, r.text
    assert r.json()["transition"]["state"] == "DRAFTING"
    approvals = (await u.get(f"/v1/projects/{pid}/approvals")).json()["items"]
    assert {a["gate"] for a in approvals if a["status"] == "valid"} >= {"H1", "H2", "H3"}


async def test_amendment_binding_and_method_switch_do_not_carry_h2_h3(client, temporal_env, open_cfp):
    u, pid, opp = await project_at_direction_review(client, temporal_env)
    await select(u, pid, "empirical_quantitative", opp)
    assert (await h1(u, pid, opp)).status_code == 200
    prot = await frozen_protocol(u, pid, temporal_env, review="waiver")
    r = await u.post(f"/v1/projects/{pid}/protocols", json={"sections": {**fx.SECTIONS, "metrics": "F1 instead of accuracy"},
                                                           "ethics_rights": fx.ETHICS})
    assert r.status_code == 422 and r.json()["error"]["code"] == "amendment_rationale_required"
    r = await u.post(f"/v1/projects/{pid}/protocols", json={
        "sections": {**fx.SECTIONS, "metrics": "F1 instead of accuracy"}, "ethics_rights": fx.ETHICS,
        "amendment_rationale": "Class imbalance discovered after inspecting the labels.", "after_data_inspection": True})
    amended = r.json()
    assert amended["is_amendment"] and amended["after_data_inspection"]
    bad = manifest(prot, [{"name": "accuracy", "value": 0.75, "unit": "proportion", "n": 8, "numerator": 6, "denominator": 8}], [])
    bad.update({"protocol_version": amended["version"], "protocol_hash": amended["content_hash"]})
    assert (await u.post(f"/v1/projects/{pid}/results", json=bad)).status_code == 422, "unapproved revision rejected"
    await u.post(f"/v1/projects/{pid}/protocols/2/waive-review", json={"rationale": "Offline colleague review of the amendment."})
    r = await u.post(f"/v1/projects/{pid}/protocols/2/approve", json={"declaration_accepted": True,
                                                                      "declaration_text": await decl(u, pid, "H2")})
    assert r.status_code == 200, r.text
    approvals = (await u.get(f"/v1/projects/{pid}/approvals")).json()["items"]
    h2 = [a for a in approvals if a["gate"] == "H2"]
    assert [a["status"] for a in h2].count("valid") == 1 and any(a["status"] == "invalidated" for a in h2)

    # Switch to a theoretical study: H1 reopens; the new method instance has no frozen protocol and other stages.
    r = await select(u, pid, "theoretical", opp, rationale="Restoration can be characterised analytically; I will argue it.")
    assert r.status_code == 201 and r.json()["switch_effects"]["invalidated_approvals"]
    proj = (await u.get(f"/v1/projects/{pid}")).json()
    assert proj["state"] == "DIRECTION_REVIEW"
    wf = (await u.get(f"/v1/projects/{pid}/workflow-definition")).json()
    assert [s["id"] for s in wf["stages"]] == ["conceptual_framework", "derivation", "evaluation"]
    assert wf["frozen_protocol_version"] is None and all(s["status"] == "blocked_until_h2" for s in wf["stages"])
    assert any(d["decision"] == "not_transferred" and "H2/H3" in d["item"] for d in wf["instance"]["reuse_decisions"])
    valid = {a["gate"] for a in (await u.get(f"/v1/projects/{pid}/approvals")).json()["items"] if a["status"] == "valid"}
    assert "H1" not in valid and "H2" not in valid


async def test_disabled_method_planning_only_and_no_screening_transfer(client, temporal_env, open_cfp):
    u, pid, opp = await project_at_direction_review(client, temporal_env)
    assert (await select(u, pid, "narrative_review", opp)).status_code == 201
    paper = (await u.get(f"/v1/projects/{pid}/papers")).json()["items"][0]
    await u.post(f"/v1/projects/{pid}/papers/{paper['id']}/screen", json={"stage": "title_abstract", "decision": "include",
                                                                         "reason": "relevant to the argument"})
    r = await select(u, pid, "systematic_review", opp, rationale="A systematic synthesis may be more convincing here.")
    inst = r.json()
    # M10 published systematic_review@2 (validated); version 1 remains planning-only for instances bound to it.
    from rp_contracts import methods as _methods

    assert inst["definition_key"] == "systematic_review@2" and inst["enabled_for_submission_ready"] is True
    v1 = _methods.REGISTRY["systematic_review@1"]
    assert v1.enabled_for_submission_ready is False and "validation" in v1.planning_only_reason
    assert any(d["decision"] == "not_transferred" and "screening" in d["item"] for d in inst["reuse_decisions"])
    papers = (await u.get(f"/v1/projects/{pid}/papers")).json()["items"]
    assert all(not p["screening"] for p in papers), "narrative screening choices are not systematic screening decisions"
