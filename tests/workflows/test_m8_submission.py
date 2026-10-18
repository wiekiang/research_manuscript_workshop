"""M8 acceptance - the first complete product objective, end to end against the fixture CFP (no gate bypass):
CFP confirmation -> literature -> H1 -> H2 -> results -> H3 -> manuscript -> independent review -> compliance against
the official snapshot rules with signed manual decisions -> integrity -> pre-approval readiness -> unapproved export
for author review -> author assent (in product + recorded offline attestation) -> H4 on a frozen content manifest ->
eligibility for the intended action -> verified package -> PACKAGE_READY. A disclosure edit invalidates H4 and the
package without touching H1-H3. Nothing is submitted externally."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from conftest import make_user
from test_m1_cfp_journey import supply_fixture
from test_m4_literature import providers, search  # noqa: F401
from test_m4_literature import run_all as run_rf
from test_m6_manuscript import run_all
from test_m7_reviews import advance, manuscript_in_review

from rp_latex.sandbox import docker_available

pytestmark = [pytest.mark.temporal, pytest.mark.docker,
              pytest.mark.skipif(not docker_available(), reason="container runtime unavailable")]


async def project_with_confirmed_cfp(client, env):
    u = await make_user(client)
    p = (await u.post("/v1/projects", json={"title": "Version drift in R", "topic": "reproducibility of data pipelines",
                                            "responsibility_acknowledged": True})).json()
    pid = p["id"]
    await supply_fixture(u, pid)
    await run_all(u, env, pid)
    cfp = (await u.get(f"/v1/projects/{pid}/cfp")).json()
    ed = cfp["editions"][0]
    research = next(t for t in ed["tracks"] if t["name"].startswith("Research"))
    r = await u.post(f"/v1/projects/{pid}/target", json={"edition_id": ed["edition"]["id"], "track_id": research["id"],
                                                         "mode": "official", "official_source_confirmed": True,
                                                         "expected_version": 1})
    assert r.status_code == 200, r.text
    for item in [x for x in (await u.get(f"/v1/projects/{pid}/cfp")).json()["editions"][0]["rules"]
                 if x["status"] == "needs_human_resolution"]:
        if item["rule_key"] == "fees.statement":
            body = {"action": "reject", "rationale": "Not stated in the official CFP."}
        elif item["rule_key"] == "deadline.full_paper":
            body = {"action": "edit", "date": "2027-01-21", "timezone": "AoE", "rationale": "Source says January 21 AoE."}
        elif item["item_type"] == "deadline":
            body = {"action": "confirm", "timezone": "UTC-12", "time": "23:59", "rationale": "The CFP states AoE."}
        else:
            body = {"action": "confirm", "rationale": "Read the official text; disclosure goes in acknowledgments."}
        r = await u.post(f"/v1/projects/{pid}/cfp/resolve", json={"rule_id": item["id"], **body})
        assert r.status_code == 200, (item["rule_key"], r.text)
    r = await u.post(f"/v1/projects/{pid}/cfp/confirm", json={"declaration_accepted": True,
                                                             "declaration_text": cfp["declaration"]["text"]})
    assert r.status_code == 200 and r.json()["state"] == "DIRECTION_REVIEW", r.text
    await search(u, pid, providers=("crossref",))
    await run_rf(u, env, pid)
    await u.post(f"/v1/projects/{pid}/opportunities/generate")
    await run_rf(u, env, pid)
    opp = (await u.get(f"/v1/projects/{pid}/opportunities")).json()["items"][0]
    return u, pid, opp


async def through_scientific_review(u, env, pid, mid):
    """Review round 1 -> accept the scientific major with a reason, fix the drifting span, recompile, re-review."""
    await u.post(f"/v1/projects/{pid}/reviews", json={})
    await run_all(u, env, pid)
    rnd = (await u.get(f"/v1/projects/{pid}/reviews")).json()["items"][0]
    drift = next(f for f in rnd["findings"] if f["category"] == "scope_drift")
    sci = next(f for f in rnd["findings"] if f["function"] == "scientific" and f["severity"] == "major")
    await u.post(f"/v1/review-findings/{sci['id']}/resolve", json={
        "resolution": "accepted_risk", "note": "The Limitations section states the sample size; we keep the framing."})
    cur = (await u.get(f"/v1/projects/{pid}/manuscript")).json()["manuscript"]["current_version"]
    key = next(s["section"] for s in cur["spans"] if s["span_id"] == drift["span_ids"][0])
    sec = next(s for s in cur["content"]["sections"] if s["key"] == key)
    for p in sec["paragraphs"]:
        for sp in p["spans"]:
            if sp["span_id"] == drift["span_ids"][0]:
                sp["text"] = drift["proposed_fix"]
    assert (await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": cur["version"], "sections": [sec]})).status_code == 200
    await u.post(f"/v1/review-findings/{drift['id']}/resolve", json={"resolution": "fixed", "note": "Used the suggested wording."})
    await u.post(f"/v1/projects/{pid}/compile", json={"anonymous": True})
    await run_all(u, env, pid)
    await u.post(f"/v1/projects/{pid}/reviews", json={})
    await run_all(u, env, pid)
    r = await advance(u, pid, "COMPLIANCE_REVIEW")
    assert r.status_code == 200, r.text
    return (await u.get(f"/v1/projects/{pid}/reviews")).json()


def authors_body(me, version=0, coauthor_name="Rosalind Byte"):
    common = {"competing_interests": "None declared", "funding": "No external funding", "human_confirmed": True}
    return {"expected_record_version": version, "authors": [
        {"name": me["display_name"], "email": me["email"], "affiliations": ["Example University"], "user_id": me["id"],
         "corresponding": True, "contribution_roles": ["conceptualization", "investigation", "writing_original_draft"],
         "contribution_statement": "Designed the study, ran the restoration analysis and wrote the manuscript.", **common},
        {"name": coauthor_name, "email": "rosalind@example.org", "affiliations": ["Example Institute"],
         "contribution_roles": ["validation", "writing_review_editing"],
         "contribution_statement": "Checked the restoration labels and revised the manuscript.", **common}]}


async def test_full_journey_to_package_ready(client, temporal_env):
    start = await project_with_confirmed_cfp(client, temporal_env)
    u, pid, mid, ids = await manuscript_in_review(client, temporal_env, start)
    reviews = await through_scientific_review(u, temporal_env, pid, mid)
    rnd = reviews["items"][0]

    # Compliance read the official rules: double-blind/abstract/page limits are machine-checked; the rest are manual.
    comp_rep = next(x for x in rnd["reports"] if x["function"] == "compliance")
    checks = {c["id"]: c for c in comp_rep["summary"]["checks"]}
    assert comp_rep["status"] == "performed" and "cfp.official_rules" not in checks
    assert checks["rule:length.page_limit"]["status"] in ("passed", "manual_check")
    assert checks["rule:abstract.word_limit"]["status"] == "passed"
    assert checks["rule:anonymization.mode"]["status"] == "passed"
    assert all(c["quote"] for k, c in checks.items() if k.startswith("rule:")), "every rule check cites the official quote"
    assert not [c for c in checks.values() if c["status"] in ("failed", "not_performed")], checks
    r = await advance(u, pid, "FINAL_APPROVAL")
    assert r.status_code in (409, 422) and "signed human resolution" in r.text
    decl = reviews["decision_declaration"]
    for c in checks.values():
        if c["status"] == "manual_check":
            r = await u.post(f"/v1/reviews/{rnd['id']}/compliance/{c['id']}/decide", json={
                "decision": "resolved", "rationale": f"Checked against the official CFP text: {c['detail'][:80]}",
                "declaration_accepted": True, "declaration_text": decl})
            assert r.status_code == 201, r.text

    # Authors (AI cannot be listed), disclosures with the venue AI policy text, then integrity.
    me = (await u.get("/v1/auth/me")).json()["user"]
    bad = authors_body(me)
    bad["authors"][1]["name"] = "ChatGPT"
    r = await u.put(f"/v1/projects/{pid}/authors", json=bad)
    assert r.status_code == 422 and any("AI tools cannot be listed" in x for x in r.json()["error"]["details"]["problems"])
    r = await u.put(f"/v1/projects/{pid}/authors", json=authors_body(me))
    assert r.status_code == 200, r.text
    authors = r.json()["authors"]
    dis = (await u.get(f"/v1/projects/{pid}/disclosures")).json()
    assert dis["venue_ai_policy_from_cfp"] and dis["ai_drafted_spans"] > 0
    disclosures = {"competing_interests": "None declared.", "funding": "No external funding.",
                   "ethics_statement": "No human participants; public source code only.",
                   "ai_use": "An AI writing assistant drafted sections from our verified claims; we reviewed and edited all text.",
                   "ai_policy_text": dis["venue_ai_policy_from_cfp"]["quote"],
                   "ai_policy_source": "ICRDS 2027 CFP (official snapshot)",
                   "ai_policy_interpretation": "Drafting assistance beyond language editing must be disclosed in the acknowledgments."}
    r = await u.put(f"/v1/projects/{pid}/disclosures", json={"expected_record_version": 0, "disclosures": disclosures})
    assert r.status_code == 200, r.text
    await u.post(f"/v1/projects/{pid}/integrity")
    await run_all(u, temporal_env, pid)
    integ = (await u.get(f"/v1/projects/{pid}/integrity")).json()
    rep = integ["items"][0]
    st = {c["id"]: c for c in rep["checks"]}
    assert st["declarations"]["status"] == "passed" and not [c for c in st.values() if c["status"] in ("failed", "not_performed")], st
    for c in st.values():
        if c["requires_decision"]:
            r = await u.post(f"/v1/integrity-reports/{rep['id']}/checks/{c['id']}/decide", json={
                "decision": "resolved", "rationale": "Reviewed: the overlapping sentence is attributed and cited.",
                "declaration_accepted": True, "declaration_text": integ["decision_declaration"]})
            assert r.status_code == 201, r.text

    # Pre-approval readiness, then FINAL_APPROVAL.
    r = await advance(u, pid, "FINAL_APPROVAL")
    assert r.status_code in (409, 422) and "pre-approval readiness" in r.text
    ra = (await u.post(f"/v1/projects/{pid}/readiness")).json()
    assert ra["stage"] == "compliance_checked", ra
    r = await advance(u, pid, "FINAL_APPROVAL")
    assert r.status_code == 200, r.text

    # Export before H4 is possible for author review, visibly unapproved.
    r = await u.post(f"/v1/projects/{pid}/packages", json={})
    assert r.status_code == 202 and r.json()["label"] == "unapproved"
    await run_all(u, temporal_env, pid)
    pk = (await u.get(f"/v1/projects/{pid}/packages")).json()["items"][0]
    assert pk["status"] == "built" and not pk["approved"] and "UNAPPROVED" in pk["name"]

    # H4 needs every author's assent to this exact version; assent is never inferred.
    h4 = (await u.get(f"/v1/projects/{pid}/content-manifest")).json()
    assert {i["role"] for i in h4["items"]} >= {"manuscript", "pdf", "bibliography", "author_record", "disclosures",
                                                 "compliance_report", "integrity_report", "readiness_assessment"}
    r = await u.post(f"/v1/projects/{pid}/final-approval", json={"declaration_accepted": True, "declaration_text": h4["declaration"]})
    assert r.status_code == 422 and len([x for x in r.json()["error"]["details"]["reasons"] if "has not approved" in x]) == 2
    texts = (await u.get(f"/v1/projects/{pid}/authors")).json()
    r = await u.post(f"/v1/projects/{pid}/authors/{authors[0]['id']}/approve", json={
        "statement_accepted": True, "statement_text": texts["author_approval_text"]})
    assert r.status_code == 201 and r.json()["method"] == "in_product"
    r = await u.post(f"/v1/projects/{pid}/authors/{authors[1]['id']}/approve", json={
        "statement_accepted": True, "statement_text": texts["offline_attestation_text"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "evidence_required"
    r = await u.post(f"/v1/projects/{pid}/authors/{authors[1]['id']}/approve", json={
        "statement_accepted": True, "statement_text": texts["offline_attestation_text"],
        "evidence": "E-mail from R. Byte approving manuscript version as circulated."})
    assert r.status_code == 201 and r.json()["method"] == "offline_attestation"
    r = await u.post(f"/v1/projects/{pid}/final-approval", json={"declaration_accepted": True, "declaration_text": h4["declaration"]})
    assert r.status_code == 200, r.text
    assert r.json()["transition"]["state"] == "APPROVED_FOR_EXPORT"

    # Eligibility for the intended action, then the verified package moves the project to PACKAGE_READY.
    r = await u.post(f"/v1/projects/{pid}/eligibility", json={"intended_action": "new_submission"})
    el = r.json()
    assert r.status_code == 201 and el["status"] == "eligible", el
    assert any(p["kind"] == "abstract_registration" for p in el["pending_prerequisites"]), "mandatory registration still due"
    assert not el["context"] and {g["kind"] for g in el["governing"]} >= {"full_paper", "abstract_registration"}
    assert "camera_ready" not in {g["kind"] for g in el["governing"]}
    got = (await u.get(f"/v1/projects/{pid}/eligibility")).json()
    assert got["recorded"]["status"] == "eligible" and got["live"]["status"] == "eligible"
    r = await u.post(f"/v1/projects/{pid}/packages", json={})
    assert r.json()["label"] == "approved"
    await run_all(u, temporal_env, pid)
    pk = (await u.get(f"/v1/projects/{pid}/packages")).json()["items"][0]
    assert pk["status"] == "verified" and pk["approved"] and len(pk["checksum"]) == 64, pk
    proj = (await u.get(f"/v1/projects/{pid}")).json()
    assert proj["state"] == "PACKAGE_READY", proj["state"]
    rd = (await u.get(f"/v1/projects/{pid}/readiness")).json()
    assert rd["current_stage"] == "submission_ready_package" and "does not submit" in rd["notice"]

    # Package bytes reproduce the signed content hashes.
    url = (await u.get(f"/v1/artifacts/{pk['artifact_id']}/download-url")).json()["url"]
    data = (await u.get(url)).content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest = json.loads(z.read("provenance-manifest.json"))
        assert "UNAPPROVED" not in z.read("README.txt").decode()
        assert {"paper.pdf", "references.bib", "authors.json", "disclosures.json", "checklist.md"} <= set(z.namelist())
    assert all(f["matches_signed_hash"] for f in manifest["files"] if f["role"] != "generated")

    # A disclosure edit invalidates H4 and the package; H1-H3 stay valid.
    r = await u.put(f"/v1/projects/{pid}/disclosures", json={"expected_record_version": 1, "disclosures": {
        **disclosures, "funding": "Supported by an Example Foundation small grant."}})
    assert r.status_code == 200
    proj = (await u.get(f"/v1/projects/{pid}")).json()
    valid = {a["gate"] for a in proj["approvals"] if a["status"] == "valid"}
    assert proj["state"] == "FINAL_APPROVAL" and "H4" not in valid and {"H1", "H2", "H3", "CFP"} <= valid
    pk = (await u.get(f"/v1/projects/{pid}/packages")).json()["items"][0]
    assert pk["stale"], "the prior package is kept for audit and visibly stale"
    assert (await u.get(f"/v1/projects/{pid}/readiness")).json()["current_stage"] != "submission_ready_package"
