"""M7 acceptance: three independent review functions (+ technical recomputation) freeze separate reports before a
meta-review; every unique critical claim/evidence pair is opened at its source and every linked span meaning-checked;
noncritical sampling is documented; an unresolved blocker/major finding prevents advancement; fixes are re-checked on
the next committed version while unchanged checks are reused; automatic revision stops after two cycles; compliance
without an official CFP is not_performed (never passed); the integrity report fails closed and needs signed decisions."""

from __future__ import annotations

import pytest
from test_m4_literature import providers  # noqa: F401  (autouse provider fixture)
from test_m5_contribution import open_cfp  # noqa: F401
from test_m6_manuscript import confirmed_acmart, project_at_drafting, run_all

from rp_latex.sandbox import docker_available

pytestmark = [pytest.mark.temporal, pytest.mark.docker,
              pytest.mark.skipif(not docker_available(), reason="container runtime unavailable")]


async def manuscript_in_review(client, env, start=None):
    """M6 path: draft, apply, fix the two defective spans, compile, advance to SCIENTIFIC_REVIEW."""
    u, pid, ids = await project_at_drafting(client, env, start)
    await u.post(f"/v1/projects/{pid}/drafts", json={})
    await run_all(u, env, pid)
    ms = (await u.get(f"/v1/projects/{pid}/manuscript")).json()
    mid, cand = ms["manuscript"]["id"], ms["candidates"][0]
    r = await u.post(f"/v1/manuscripts/{mid}/candidates/{cand['id']}/apply")
    assert r.status_code == 200, r.text
    v = (await u.get(f"/v1/manuscripts/{mid}/versions/{r.json()['version']}")).json()
    secs = {s["key"]: s for s in v["content"]["sections"]}
    for p in secs["discussion"]["paragraphs"]:
        for sp in p["spans"]:
            if "fills the gap" in sp["text"]:
                sp["text"], sp["kind"] = "These results partly address the gap for R pipelines only.", "interpretation"
    for p in secs["related_work"]["paragraphs"]:
        p["spans"] = [sp for sp in p["spans"] if "most widely used" not in sp["text"]]
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": v["version"],
                                                     "sections": [secs["discussion"], secs["related_work"]]})
    assert r.status_code == 200 and r.json()["checks"]["blockers"] == 0, r.text
    await confirmed_acmart(u, env, pid)
    await u.post(f"/v1/projects/{pid}/compile", json={"anonymous": True})
    await run_all(u, env, pid)
    proj = (await u.get(f"/v1/projects/{pid}")).json()
    r = await u.post(f"/v1/projects/{pid}/advance", json={"requested_state": "SCIENTIFIC_REVIEW", "expected_version": proj["version"]})
    assert r.status_code == 200, r.text
    return u, pid, mid, ids


async def advance(u, pid, target):
    proj = (await u.get(f"/v1/projects/{pid}")).json()
    return await u.post(f"/v1/projects/{pid}/advance", json={"requested_state": target, "expected_version": proj["version"]})


async def test_independent_reviews_findings_rereview_and_integrity(client, temporal_env, open_cfp):  # noqa: F811
    u, pid, mid, ids = await manuscript_in_review(client, temporal_env)
    lit, res_claim = ids["literature"]["claim_key"], ids["result_claim"]["claim_key"]

    r = await advance(u, pid, "COMPLIANCE_REVIEW")
    assert r.status_code in (409, 422) and "run the independent review" in r.text

    assert (await u.post(f"/v1/projects/{pid}/reviews", json={})).status_code == 202
    tasks = await run_all(u, temporal_env, pid)
    assert next(t for t in tasks if t["kind"] == "review_run")["state"] == "succeeded"
    rnd = (await u.get(f"/v1/projects/{pid}/reviews")).json()["items"][0]
    assert rnd["status"] == "complete" and rnd["meta"] is not None
    reports = {x["function"]: x for x in rnd["reports"]}
    assert set(reports) == {"scientific", "citation_evidence", "technical", "compliance"}
    assert len({x["artifact_id"] for x in rnd["reports"]}) == 4, "reports are frozen separately"
    assert reports["scientific"]["status"] == "performed" and reports["citation_evidence"]["status"] == "performed"

    # Citation/evidence: the critical result claim and the sampled literature claim were opened at their sources.
    checks = {c["claim_key"]: c for c in rnd["claim_checks"]}
    assert checks[res_claim]["critical"] and checks[res_claim]["selection"] == "critical"
    assert checks[res_claim]["source_status"] == "passed"
    assert checks[lit]["selection"] == "sampled" and checks[lit]["source_status"] == "passed"
    assert all(m["verdict"] for c in checks.values() for m in c["meaning"])
    cs = reports["citation_evidence"]["summary"]
    assert cs["sampling_rule"] == "risk-sample-v1" and cs["unchecked_noncritical"] == []
    tech = reports["technical"]["summary"]["results"][ids["result_key"]]
    assert tech["recomputation"] == "passed" and tech["assurance"] == "independently_checked"

    # Compliance without an official CFP snapshot is not_performed, never passed.
    comp = {c["id"]: c for c in reports["compliance"]["summary"]["checks"]}
    assert comp["cfp.official_rules"]["status"] == "not_performed" and reports["compliance"]["status"] == "partial"
    assert comp["compile.current_version"]["status"] == "passed"

    findings = rnd["findings"]
    drift = next(f for f in findings if f["function"] == "citation_evidence" and f["category"] == "scope_drift")
    sci = next(f for f in findings if f["function"] == "scientific" and f["severity"] == "major")
    assert drift["severity"] == "major" and drift["span_ids"] and drift["proposed_fix"]
    assert rnd["meta"]["counts"]["citation_evidence"]["major"] >= 1
    assert "not an acceptance decision" in rnd["meta"]["note"]

    r = await advance(u, pid, "COMPLIANCE_REVIEW")
    assert r.status_code in (409, 422) and "open blocker/major" in r.text

    # Automatic revision is capped at two cycles; its output is only a candidate for explicit human apply/merge.
    for n in (1, 2):
        r = await u.post(f"/v1/reviews/{rnd['id']}/revise", json={})
        assert r.status_code == 202, r.text
        assert r.json()["cycle"] == n and r.json()["remaining"] == 2 - n and r.json()["sections"]
        c = await u.post(f"/v1/projects/{pid}/tasks/{r.json()['task']['id']}/cancel")
        assert c.status_code == 202, c.text
    r = await u.post(f"/v1/reviews/{rnd['id']}/revise", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "revision_limit_reached"
    assert (await u.get(f"/v1/projects/{pid}/reviews")).json()["revision_cycles"] == {"used": 2, "limit": 2}
    tasks = await run_all(u, temporal_env, pid)
    gens = [t for t in tasks if t["kind"] == "manuscript_generation" and "review findings" in (t["params"].get("instructions") or "")]
    assert len(gens) == 2 and all(t["state"] in ("cancelled", "failed_terminal") for t in gens)
    ms = (await u.get(f"/v1/projects/{pid}/manuscript")).json()
    assert ms["manuscript"]["current_version"]["origin"] != "candidate_applied", "revisions are never auto-applied"
    assert {c["status"] for c in ms["candidates"] if c["task_id"] in {t["id"] for t in gens}} <= {"pending", "failed"}

    # Resolution rules: 'fixed' needs a newer version; a scientific major may be accepted only with a reason.
    r = await u.post(f"/v1/review-findings/{drift['id']}/resolve", json={"resolution": "fixed", "note": "reworded"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_newer_version"
    r = await u.post(f"/v1/review-findings/{sci['id']}/resolve", json={"resolution": "accepted_risk", "note": "ok"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "rationale_required"
    r = await u.post(f"/v1/review-findings/{sci['id']}/resolve", json={
        "resolution": "accepted_risk", "note": "The Limitations section states the sample size; we keep the framing."})
    assert r.status_code == 200 and r.json()["status"] == "accepted_risk"

    # The author fixes the drifting span; the next round re-checks it and reuses the unchanged check.
    cur = (await u.get(f"/v1/projects/{pid}/manuscript")).json()["manuscript"]["current_version"]
    sec_key = next(s["section"] for s in cur["spans"] if s["span_id"] == drift["span_ids"][0])
    sec = next(s for s in cur["content"]["sections"] if s["key"] == sec_key)
    for p in sec["paragraphs"]:
        for sp in p["spans"]:
            if sp["span_id"] == drift["span_ids"][0]:
                sp["text"] = drift["proposed_fix"]
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": cur["version"], "sections": [sec]})
    assert r.status_code == 200, r.text
    r = await u.post(f"/v1/review-findings/{drift['id']}/resolve", json={"resolution": "fixed", "note": "Used the suggested wording."})
    assert r.status_code == 200
    r = await advance(u, pid, "COMPLIANCE_REVIEW")
    assert r.status_code in (409, 422) and "on the current manuscript version" in r.text, "reviews apply only to their version"

    assert (await u.post(f"/v1/projects/{pid}/reviews", json={})).status_code == 202
    await run_all(u, temporal_env, pid)
    rnd2 = (await u.get(f"/v1/projects/{pid}/reviews")).json()["items"][0]
    assert rnd2["id"] != rnd["id"] and rnd2["status"] == "complete"
    c2 = {c["claim_key"]: c for c in rnd2["claim_checks"]}
    assert c2[res_claim]["reused"], "unchanged claim/source/spans reuse the prior check"
    assert not c2[lit]["reused"] and all(m["verdict"] == "faithful" for m in c2[lit]["meaning"])
    carried = [f for f in rnd2["findings"] if f["function"] == "scientific" and f["severity"] == "major"]
    assert carried and carried[0]["status"] == "accepted_risk" and carried[0]["resolution_note"].startswith("carried forward")
    assert not [f for f in rnd2["findings"] if f["status"] == "open" and f["severity"] in ("blocker", "major")
                and f["function"] != "compliance"]
    r = await advance(u, pid, "COMPLIANCE_REVIEW")
    assert r.status_code == 200, r.text

    # Compliance gate: not_performed blocks; integrity: declarations pending (M8) block, warnings need signed decisions.
    r = await advance(u, pid, "FINAL_APPROVAL")
    assert r.status_code in (409, 422) and "cfp.official_rules" in r.text
    assert (await u.post(f"/v1/projects/{pid}/integrity")).status_code == 202
    await run_all(u, temporal_env, pid)
    rep = (await u.get(f"/v1/projects/{pid}/integrity")).json()
    report = rep["items"][0]
    st = {c["id"]: c for c in report["checks"]}
    assert st["references.identity"]["status"] == "passed" and st["claims.supported"]["status"] == "passed"
    assert st["results.wording_vs_assurance"]["status"] == "passed" and st["results.provenance"]["status"] == "passed"
    assert st["text.overlap"]["limitations"].endswith("not comprehensive plagiarism detection.")
    assert "does not certify" in report["summary"]["disclaimer"]
    for cid, c in st.items():
        if c["status"] in ("failed",):
            r = await u.post(f"/v1/integrity-reports/{report['id']}/checks/{cid}/decide", json={
                "decision": "accepted_risk", "rationale": "x" * 30, "declaration_accepted": True,
                "declaration_text": rep["decision_declaration"]})
            assert r.status_code == 409, "a failed integrity check cannot be waived"
    pending = [cid for cid, c in st.items() if c["requires_decision"]]
    for cid in pending:
        r = await u.post(f"/v1/integrity-reports/{report['id']}/checks/{cid}/decide", json={
            "decision": "resolved", "rationale": "Reviewed the evidence for this check.", "declaration_accepted": True,
            "declaration_text": "I agree"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "declaration_mismatch"
