"""Table result-key validation through the edit/commit path (M6).

Traces check_tables (contracts) -> commit_version (checks_summary.table_issues, blockers) -> the manuscript.complete
gate. A table citing a result key that is not a committed result is reported as a located blocker on the committed
version and blocks DRAFTING -> SCIENTIFIC_REVIEW; a table citing a committed result is clean and completion proceeds.
State below H3 is fabricated directly (method instance, protocol, committed result, H3 approval), as other API tests
do; the manuscript itself is edited through the public PATCH endpoint.
"""

from __future__ import annotations

import uuid

from conftest import make_project, make_user

SECTION_TEXT = {
    "abstract": "This study examines version records for broken analysis pipelines.",
    "introduction": "Silent dependency upgrades break published analyses.",
    "related_work": "Earlier work catalogued breakage without repair strategies.",
    "method": "Eight public R pipelines were rerun from their version records.",
    "results": "The outcomes are summarised in the table below.",
    "discussion": "Restoration worked for most pipelines in this sample.",
    "limitations": "Only eight pipelines from one ecosystem were studied.",
    "conclusion": "Version records are a practical restoration aid for this sample.",
}


def section(key: str, tables: list[dict] | None = None) -> dict:
    return {"key": key, "heading": key.replace("_", " ").title(),
            "paragraphs": [{"spans": [{"span_id": "", "text": SECTION_TEXT[key], "kind": "framing"}]}],
            "tables": tables or []}


async def project_at_drafting_with_result(u, project_id: str) -> str:
    """DRAFTING project with an active method instance, one committed result (RES-001), a valid H3 approval
    (=> paper mode) and the skeleton manuscript v1. Returns the manuscript id."""
    from sqlalchemy import select

    from rp_api.db.engine import session_scope
    from rp_api.db.models.contribution import MethodWorkflowInstance, Protocol, ResultManifestRecord
    from rp_api.db.models.core import Approval, Project
    from rp_api.features.manuscript import get_or_create_manuscript
    from rp_api.security.tokens import Principal

    pid, tid, uid = uuid.UUID(project_id), uuid.UUID(u.tenant_id), uuid.UUID(u.user_id)
    actor = Principal(kind="user", subject=u.email, user_id=uid, tenant_id=tid, tenant_role="owner")
    async with session_scope("system") as db:
        project = (await db.execute(select(Project).where(Project.id == pid))).scalar_one()
        project.state = "DRAFTING"
        inst = MethodWorkflowInstance(tenant_id=tid, project_id=pid, definition_key="empirical_quantitative.v1",
                                      study_type="empirical_quantitative", definition_version=1,
                                      venue_category="conference", enabled_for_submission_ready=True,
                                      status="active", selected_by=uid)
        db.add(inst)
        await db.flush()
        prot = Protocol(tenant_id=tid, project_id=pid, method_instance_id=inst.id, version_number=1,
                        status="frozen", sections={}, artifact_id=uuid.uuid4(), content_hash="a" * 64,
                        created_by=uid)
        db.add(prot)
        await db.flush()
        db.add(ResultManifestRecord(tenant_id=tid, project_id=pid, method_instance_id=inst.id, protocol_id=prot.id,
                                    result_key="RES-001", title="Restoration accuracy",
                                    manifest={"metrics": [{"name": "accuracy", "value": 0.75, "unit": "proportion",
                                                           "n": 8, "numerator": 6, "denominator": 8}]},
                                    artifact_id=uuid.uuid4(), assurance_level="independently_checked",
                                    is_current=True))
        # A valid H3 approval with no bound artifacts: current_approval returns it with no problems => paper mode.
        db.add(Approval(tenant_id=tid, project_id=pid, gate="H3", status="valid", approver_id=uid,
                        approver_role="owner", declaration_text="test H3 declaration", declaration_version="test",
                        content_manifest_hash="b" * 64, project_version=project.version))
        m = await get_or_create_manuscript(db, actor, project)
        mid = str(m.id)
        await db.commit()
    return mid


async def seed_verified_literature_claim(u, project_id: str) -> str:
    """A gate-eligible literature claim supported by an identity-verified paper, so the claim resolves to a
    bibliography entry (the evidence link a prior-work span relies on). Returns the claim key."""
    from rp_api.db.engine import session_scope
    from rp_api.db.models.literature import Claim, ClaimDecision, ClaimSupport, TenantPaperRecord
    from rp_api.services import claims as claim_svc

    pid, tid = uuid.UUID(project_id), uuid.UUID(u.tenant_id)
    async with session_scope("system") as db:
        paper = TenantPaperRecord(tenant_id=tid, project_id=pid, doi="10.1000/vrec", title="Version records for pipelines",
                                  authors=["Ada Lovelace"], year=2020, venue="VLDB", identity_status="verified",
                                  added_by="test")
        claim = Claim(tenant_id=tid, project_id=pid, claim_key="CLM-0001",
                      proposition="Version records restored most broken pipelines.", kind="literature",
                      category="descriptive", critical=False, status="verified", created_by="test",
                      gate_eligible=True)
        db.add_all([paper, claim])
        await db.flush()
        db.add(ClaimSupport(tenant_id=tid, claim_id=claim.id, paper_id=paper.id, relation="supports",
                            bibliographic_identity_verified=True, passage_verified=True,
                            claim_support_validated=True, is_current=True))
        # gate_eligible() reads the current decision under the active policy, not the denormalised column.
        policy = await claim_svc.active_policy(db)
        db.add(ClaimDecision(tenant_id=tid, claim_id=claim.id, policy_version=policy.version, rule_id="literature",
                             status="verified", state="current", decided_by="test"))
        await db.commit()
    return "CLM-0001"


async def rendered_results_text(client, project_id: str, version_id: str) -> str:
    """The compiled paragraph text of the results section, where a span's claim IDs become citation markers."""
    r = await client.post("/v1/internal/auth/token", json={"client_id": "research-worker",
                                                           "client_secret": "dev-research-worker-secret",
                                                           "purpose": "project", "project_id": project_id})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await client.get(f"/v1/internal/projects/{project_id}/manuscript-render",
                         params={"version_id": version_id, "anonymous": "true"}, headers=h)
    assert r.status_code == 200, r.text
    sec = next(s for s in r.json()["document"]["sections"] if s["label"] == "sec:results")
    return next(b["text"] for b in sec["blocks"] if b["type"] == "paragraph")


async def committed(u, manuscript_id: str, number: int) -> dict:
    """A committed version with its span rows and content (the PATCH response carries neither)."""
    r = await u.get(f"/v1/manuscripts/{manuscript_id}/versions/{number}")
    assert r.status_code == 200, r.text
    return r.json()


async def advance(u, project_id: str):
    proj = (await u.get(f"/v1/projects/{project_id}")).json()
    return await u.post(f"/v1/projects/{project_id}/advance",
                        json={"requested_state": "SCIENTIFIC_REVIEW", "expected_version": proj["version"]})


async def test_editing_a_table_preserves_the_annotated_spans_claims_and_evidence_links(client):
    """A section holding both an annotated span and a result table: changing only the table must not disturb the
    span's claim IDs, result keys, provenance, span identity, or the citation its claim resolves to."""
    u = await make_user(client)
    p = await make_project(u)
    mid = await project_at_drafting_with_result(u, p["id"])
    claim_key = await seed_verified_literature_claim(u, p["id"])

    annotated = {"span_id": "", "kind": "observed_result",
                 "text": "Version records restored most of the audited pipelines in this sample.",
                 "claim_ids": [claim_key], "result_keys": ["RES-001"]}
    results = {"key": "results", "heading": "Results", "paragraphs": [{"spans": [annotated]}],
               "tables": [{"caption": "Accuracy", "result_keys": ["RES-001"]},
                          {"caption": "Broken", "result_keys": ["RES-404"]}]}
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 1, "sections": [results]})
    assert r.status_code == 200, r.text
    assert r.json()["checks"]["table_issues"][0]["caption"] == "Broken"
    v2 = await committed(u, mid, 2)
    before = next(s for s in v2["spans"] if s["section"] == "results")
    assert before["claim_ids"] == [claim_key] and before["result_keys"] == ["RES-001"]
    assert before["issues"] == [], "the annotated span itself is clean; only the table is broken"

    # The rendered span carries the citation its claim resolves to (rendering also materialises the entry).
    assert (await rendered_results_text(client, p["id"], v2["id"])).endswith("[@lovelace2020version]")
    bib = (await u.get(f"/v1/projects/{p['id']}/manuscript")).json()["bibliography"]
    assert [b["cite_key"] for b in bib] == ["lovelace2020version"], bib

    # Fix only the table, resending the section exactly as the editor round-trips it (span text and id unchanged).
    fixed = {**results, "paragraphs": [{"spans": [{**annotated, "span_id": before["span_id"]}]}],
             "tables": [{"caption": "Accuracy", "result_keys": ["RES-001"]},
                        {"caption": "Broken", "result_keys": ["RES-001", "RES-001"]}]}
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 2, "sections": [fixed],
                                                      "summary": "corrected the broken table"})
    assert r.status_code == 200, r.text
    v3 = await committed(u, mid, 3)

    # The table change landed...
    assert v3["checks"]["table_issues"] == [] and v3["checks"]["blockers"] == 0, v3["checks"]
    tables = next(s for s in v3["content"]["sections"] if s["key"] == "results")["tables"]
    assert [t["result_keys"] for t in tables] == [["RES-001"], ["RES-001", "RES-001"]], tables

    # ...and the annotated span came through it untouched: same identity, links, kind and provenance.
    after = next(s for s in v3["spans"] if s["section"] == "results")
    assert after["claim_ids"] == [claim_key] and after["result_keys"] == ["RES-001"]
    assert after["span_id"] == before["span_id"], "a table edit must not re-mint the span the annotations hang on"
    assert (after["kind"], after["origin"], after["protected"]) == (before["kind"], before["origin"], before["protected"])
    assert after["issues"] == [] and v3["checks"]["spans_with_issues"] == 0
    assert after["text"] == before["text"]

    # The evidence link still renders as the same citation on the committed version.
    assert (await rendered_results_text(client, p["id"], v3["id"])).endswith("[@lovelace2020version]")


async def test_unknown_table_result_key_is_reported_on_commit_and_blocks_completion(client):
    u = await make_user(client)
    p = await make_project(u)
    mid = await project_at_drafting_with_result(u, p["id"])

    # Fill every section through the public edit path; the results section carries one valid and one broken table.
    sections = [section(k) for k in SECTION_TEXT if k != "results"]
    sections.append(section("results", tables=[{"caption": "Accuracy", "result_keys": ["RES-001"]},
                                               {"caption": "Broken", "result_keys": ["RES-404"]}]))
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 1, "sections": sections})
    assert r.status_code == 200, r.text
    checks = r.json()["checks"]

    # The committed version's check summary locates the offending table; the valid table contributes nothing.
    assert checks["table_issues"] == [{
        "section": "results", "table_index": 1, "caption": "Broken", "code": "unknown_table_result",
        "severity": "blocker",
        "message": "RES-404 is not a committed result; the table would render with no rows for it",
    }], checks
    assert checks["blockers"] == 1 and checks["spans_with_issues"] == 0 and checks["unresolved_claims"] == 0, checks

    # The same summary is read back by consumers of the version, not just the PATCH response.
    v = (await u.get(f"/v1/manuscripts/{mid}/versions/2")).json()
    assert v["checks"]["table_issues"][0]["code"] == "unknown_table_result"

    # manuscript.complete reads the blocker from checks_summary and refuses DRAFTING -> SCIENTIFIC_REVIEW.
    r = await advance(u, p["id"])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "gate_unsatisfied"
    gate = next(g for g in r.json()["error"]["details"]["gates"] if g["gate_id"] == "manuscript.complete")
    assert gate["passed"] is False
    assert any("cite results that are not committed" in x and "results/Broken" in x for x in gate["reasons"]), gate

    # Replacing the broken table with the valid one clears the issue; the gate then passes and the project advances.
    r = await u.patch(f"/v1/manuscripts/{mid}", json={
        "expected_version": 2,
        "sections": [section("results", tables=[{"caption": "Accuracy", "result_keys": ["RES-001"]}])]})
    assert r.status_code == 200, r.text
    checks = r.json()["checks"]
    assert checks["table_issues"] == [] and checks["blockers"] == 0, checks

    r = await advance(u, p["id"])
    assert r.status_code == 200, r.text
    assert (await u.get(f"/v1/projects/{p['id']}")).json()["state"] == "SCIENTIFIC_REVIEW"
