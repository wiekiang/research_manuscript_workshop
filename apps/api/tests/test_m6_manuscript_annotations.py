"""Annotation-only manuscript edits (M6).

Re-kinding a sentence or re-pointing its claim/result links changes no prose. Such an edit must still land in the
committed version, in the version diff and in the contribution ledger, and must protect the curated links from
regeneration -- without relabelling AI-drafted prose as human-authored.
"""

from __future__ import annotations

import uuid

from conftest import make_project, make_user
from test_m6_manuscript_tables import (
    committed,
    project_at_drafting_with_result,
    seed_verified_literature_claim,
)

AI_TEXT = "Version records restored most of the audited pipelines in this sample."


async def seed_ai_section(u, project_id: str, manuscript_id: str, claim_key: str) -> dict:
    """Commit a results section as an applied AI draft, so the span carries origin 'ai' as generation leaves it."""
    from sqlalchemy import select

    from rp_api.db.engine import session_scope
    from rp_api.db.models.core import Project
    from rp_api.db.models.manuscript import Manuscript
    from rp_api.features.manuscript import commit_version
    from rp_api.security.tokens import Principal
    from rp_contracts.manuscript import Paragraph, Span, TableRef

    pid, tid, uid = uuid.UUID(project_id), uuid.UUID(u.tenant_id), uuid.UUID(u.user_id)
    actor = Principal(kind="user", subject=u.email, user_id=uid, tenant_id=tid, tenant_role="owner")
    async with session_scope("system") as db:
        project = (await db.execute(select(Project).where(Project.id == pid))).scalar_one()
        m = (await db.execute(select(Manuscript).where(Manuscript.id == uuid.UUID(manuscript_id)))).scalar_one()
        _, content = await _current(db, m)
        results = content.section("results")
        results.paragraphs = [Paragraph(spans=[
            Span(span_id="S-ai", text=AI_TEXT, kind="observed_result", claim_ids=[claim_key],
                 result_keys=["RES-001"], origin="ai", protected=False),
            Span(span_id="S-ai2", text="The remaining pipelines are discussed below.", kind="framing", origin="ai"),
        ])]
        results.tables = [TableRef(caption="Accuracy", result_keys=["RES-001"])]
        await commit_version(db, actor, project, m, content, origin="candidate_applied", summary="applied draft")
        await db.commit()
    return {"span_id": "S-ai"}


async def _current(db, m):
    from rp_api.features.manuscript import current_content

    return await current_content(db, m)


def results_section(spans: list[dict], tables: list[dict] | None = None) -> dict:
    return {"key": "results", "heading": "Results", "paragraphs": [{"spans": spans}],
            "tables": tables if tables is not None else [{"caption": "Accuracy", "result_keys": ["RES-001"]}]}


async def ledger_entries(u, project_id: str) -> list[dict]:
    r = await u.get(f"/v1/projects/{project_id}/contribution-ledger")
    assert r.status_code == 200, r.text
    return [e for e in r.json()["items"] if e["source_action"] == "manuscript.edit"]


async def test_relinking_a_span_is_committed_diffed_and_ledgered_without_relabelling_the_prose(client):
    u = await make_user(client)
    p = await make_project(u)
    mid = await project_at_drafting_with_result(u, p["id"])
    claim_key = await seed_verified_literature_claim(u, p["id"])
    await seed_ai_section(u, p["id"], mid, claim_key)

    v2 = await committed(u, mid, 2)
    before = next(s for s in v2["spans"] if s["span_id"] == "S-ai")
    assert (before["origin"], before["protected"]) == ("ai", False)
    assert before["claim_ids"] == [claim_key] and before["kind"] == "observed_result"

    # Same prose, re-pointed evidence: drop the result link and soften the kind.
    relinked = {"span_id": "S-ai", "text": AI_TEXT, "kind": "interpretation", "claim_ids": [claim_key],
                "result_keys": []}
    untouched = {"span_id": "S-ai2", "text": "The remaining pipelines are discussed below.", "kind": "framing",
                 "claim_ids": [], "result_keys": []}
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 2,
                                                      "sections": [results_section([relinked, untouched])]})
    assert r.status_code == 200, r.text

    v3 = await committed(u, mid, 3)
    after = next(s for s in v3["spans"] if s["span_id"] == "S-ai")
    # The edit is committed...
    assert after["kind"] == "interpretation" and after["result_keys"] == [] and after["claim_ids"] == [claim_key]
    # ...the prose keeps its real author, but the curation is now protected from regeneration...
    assert after["origin"] == "ai", "an annotation edit must not relabel AI-drafted prose as human-authored"
    assert after["protected"] is True
    assert after["text"] == before["text"] and after["span_id"] == before["span_id"]
    # ...and the sentence nobody touched is untouched.
    other = next(s for s in v3["spans"] if s["span_id"] == "S-ai2")
    assert (other["origin"], other["protected"]) == ("ai", False)

    # Reviewable in version history and in the ledger, with the before/after of the links in the diff.
    assert "relinked" in v3["change_summary"], v3["change_summary"]
    entry = (await ledger_entries(u, p["id"]))[0]
    assert "1 sentence(s) relinked" in entry["summary"], entry["summary"]
    assert "-" + AI_TEXT + " [observed_result; claims CLM-0001; results RES-001]" in entry["diff"]
    assert "+" + AI_TEXT + " [interpretation; claims CLM-0001]" in entry["diff"]
    assert "Relinked:" in entry["diff"] and "kind observed_result -> interpretation" in entry["diff"]


async def test_an_ordinary_text_edit_still_reads_as_a_prose_change(client):
    u = await make_user(client)
    p = await make_project(u)
    mid = await project_at_drafting_with_result(u, p["id"])
    claim_key = await seed_verified_literature_claim(u, p["id"])
    await seed_ai_section(u, p["id"], mid, claim_key)

    rewritten = {"span_id": "S-ai", "text": "Version records restored six of the eight audited pipelines.",
                 "kind": "observed_result", "claim_ids": [claim_key], "result_keys": ["RES-001"]}
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 2, "sections": [results_section([rewritten])]})
    assert r.status_code == 200, r.text

    v3 = await committed(u, mid, 3)
    span = next(s for s in v3["spans"] if s["text"].startswith("Version records restored six"))
    # Rewritten prose is authored by the editor and gets a fresh identity; links ride along unchanged.
    assert (span["origin"], span["protected"]) == ("human", True)
    assert span["span_id"] != "S-ai"
    assert span["claim_ids"] == [claim_key] and span["result_keys"] == ["RES-001"]

    entry = (await ledger_entries(u, p["id"]))[0]
    assert "relinked" not in entry["summary"], "a prose rewrite is not a relink"
    assert "Relinked:" not in (entry["diff"] or "")
    assert "-" + AI_TEXT in entry["diff"] and "+Version records restored six of the eight audited pipelines." in entry["diff"]
