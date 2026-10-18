"""M6 acceptance: draft spans cite claim/result IDs and the bibliography comes only from identity-verified papers
supporting cited claims; unsupported factual sentences enter the unresolved-claim queue and an overstated gap claim
blocks completion; an author edit during generation leaves a stale candidate that cannot be applied, and only an
explicit merge creates a new version that keeps the human text; the committed version compiles in the sandbox."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from conftest import drain_outbox
from temporalio.worker import Worker
from test_m4_literature import providers, upload_known_paper  # noqa: F401  (autouse provider fixture)
from test_m5_contribution import (
    PRED,
    contribute,
    decl,
    frozen_protocol,
    h1,
    manifest,
    open_cfp,  # noqa: F401
    project_at_direction_review,
    select,
)

from rp_contracts.tasks import QUEUE_EXPERIMENT, QUEUE_FETCH, QUEUE_LATEX, QUEUE_RESEARCH
from rp_latex.sandbox import docker_available
from rp_research.registry import ACTIVITIES, WORKFLOWS, load_features

pytestmark = [pytest.mark.temporal, pytest.mark.docker,
              pytest.mark.skipif(not docker_available(), reason="container runtime unavailable")]
FIX = Path(__file__).resolve().parents[2] / "tests/fixtures/templates"
load_features()


async def run_all(u, env, pid, timeout=180):
    ws = [Worker(env.client, task_queue=q, workflows=WORKFLOWS[q], activities=ACTIVITIES[q])
          for q in (QUEUE_RESEARCH, QUEUE_FETCH, QUEUE_LATEX, QUEUE_EXPERIMENT)]
    deadline = time.monotonic() + timeout
    async with ws[0], ws[1], ws[2], ws[3]:
        while time.monotonic() < deadline:
            await drain_outbox(env)
            tasks = (await u.get(f"/v1/projects/{pid}/tasks")).json()["items"]
            if tasks and all(t["state"] in ("succeeded", "failed_terminal", "cancelled") for t in tasks):
                return tasks
            await asyncio.sleep(0.1)
    raise AssertionError([(t["kind"], t["state"]) for t in tasks])


async def confirmed_acmart(u, env, pid):
    r = await u.post(f"/v1/projects/{pid}/templates/upload",
                     files={"file": ("acmart.zip", (FIX / "acmart.zip").read_bytes(), "application/zip")},
                     data={"declared_origin_url": "https://mirrors.ctan.org/macros/latex/contrib/acmart.zip",
                           "origin_statement": "Official ACM consolidated template distribution (CTAN).",
                           "mode": "submission", "license_note": "LPPL 1.3c", "attest_official": "true"})
    assert r.status_code == 202, r.text
    tid = r.json()["template_id"]
    await run_all(u, env, pid)
    r = await u.post(f"/v1/projects/{pid}/templates/{tid}/confirm", json={"declaration_accepted": True})
    assert r.status_code == 200, r.text
    return tid


async def project_at_drafting(client, env, start=None):
    """The M5 empirical path to H3, plus one identity-verified paper with a verified literature claim."""
    u, pid, opp = start or await project_at_direction_review(client, env)
    await upload_known_paper(u, pid)
    await run_all(u, env, pid)
    lit = next(c for c in (await u.get(f"/v1/projects/{pid}/evidence")).json()["claims"] if c["category"] == "descriptive")
    await u.post(f"/v1/claims/{lit['id']}/verify", json={"request_model_assessment": True})
    await run_all(u, env, pid)
    assert (await select(u, pid, "empirical_quantitative", opp)).status_code == 201
    assert (await h1(u, pid, opp)).status_code == 200
    prot = await frozen_protocol(u, pid, env, review="model")
    preds = await contribute(u, pid, "predictions.csv", PRED)
    raw = await contribute(u, pid, "labels.csv", b"pipeline,restored\nA,1\n", ctype="dataset")
    files = [{"role": "predictions", "artifact_id": preds["artifact_id"]}, {"role": "raw_data", "artifact_id": raw["artifact_id"]}]
    acc = [{"name": "accuracy", "value": 0.75, "unit": "proportion", "n": 8, "numerator": 6, "denominator": 8}]
    r1 = (await u.post(f"/v1/projects/{pid}/results", json=manifest(prot, acc, files))).json()
    await run_all(u, env, pid)
    await u.post(f"/v1/projects/{pid}/method-stages/data_provenance", json={"description": "", "fields": {
        "data_origin": "eight public R pipelines from CRAN task views", "selection_criteria": "public inputs, no credentials",
        "pii_classification": "none", "rights": "MIT/GPL"}, "contribution_ids": [raw["id"]]})
    await u.post(f"/v1/projects/{pid}/method-stages/analysis", json={"description": "", "result_ids": [r1["id"]]})
    s = await u.post(f"/v1/projects/{pid}/method-stages/result_checks", json={"description": "", "result_ids": [r1["id"]]})
    assert s.json()["transition"]["state"] == "OUTCOME_REVIEW", s.json()
    c = (await u.post(f"/v1/projects/{pid}/results/{r1['id']}/claims", json={
        "proposition": "The restoration classifier reached 0.75 accuracy (6/8) on the eight pipelines.",
        "metric_name": "accuracy", "researcher_confirms_match": True})).json()
    row = (await u.get(f"/v1/projects/{pid}/contribution-matrix")).json()["items"][0]
    r = await u.post(f"/v1/projects/{pid}/contribution-matrix/review", json={"rows": [{
        **{k: row[k] for k in ("rq_index", "research_question", "intended_novelty", "intended_contribution", "success_criterion")},
        "evidence_ids": [r1["result_key"], c["claim_key"]], "outcome": "partially_supported",
        "validity_assessment": "Small sample; supports restoration for most but not all pipelines.",
        "limitations": "n=8", "h3_decision": "accepted"}]})
    assert r.status_code == 200, r.text
    await u.post(f"/v1/projects/{pid}/gap-resolution", json={"status": "partially_addressed", "supporting_ids": [c["claim_key"]],
                                                            "explanation": "Only R and a small sample were studied."})
    r = await u.post(f"/v1/projects/{pid}/results/approve", json={
        "interpretation": "Version records restored most affected R pipelines in this small exploratory sample.",
        "limitations": "Eight pipelines; exploratory framing.", "anomalies_reviewed": True,
        "declaration_accepted": True, "declaration_text": await decl(u, pid, "H3")})
    assert r.json()["transition"]["state"] == "DRAFTING", r.text
    return u, pid, {"literature": lit, "result_claim": c, "result_key": r1["result_key"]}


def spans(version):
    return version["spans"]


def section_payload(version, key):
    return next(s for s in version["content"]["sections"] if s["key"] == key)


async def test_grounded_draft_stale_candidate_merge_and_compile(client, temporal_env, open_cfp):  # noqa: F811
    u, pid, ids = await project_at_drafting(client, temporal_env)
    assert (await u.get(f"/v1/projects/{pid}/manuscript")).json()["manuscript"] is None

    # Request a full draft; before the worker runs, the author edits the introduction (manuscript v1 -> v2).
    r = await u.post(f"/v1/projects/{pid}/drafts", json={})
    assert r.status_code == 202, r.text
    assert r.json()["mode"] == "paper" and r.json()["base_version"] == 1
    ms = (await u.get(f"/v1/projects/{pid}/manuscript")).json()
    mid = ms["manuscript"]["id"]
    human = "We began this study after losing a week to a silently upgraded R package."
    intro = {"key": "introduction", "heading": "Introduction",
             "paragraphs": [{"spans": [{"span_id": "", "text": human, "kind": "framing"}]}]}
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 1, "sections": [intro]})
    assert r.status_code == 200 and r.json()["version"] == 2, r.text
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 1, "sections": [intro]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_version"

    tasks = await run_all(u, temporal_env, pid)
    gen = next(t for t in tasks if t["kind"] == "manuscript_generation")
    assert gen["state"] == "succeeded", gen
    ms = (await u.get(f"/v1/projects/{pid}/manuscript")).json()
    cand = ms["candidates"][0]
    assert cand["status"] == "stale", "output generated against v1 must not be treated as current"
    assert ms["manuscript"]["current_version"]["version"] == 2, "nothing was silently overwritten"
    r = await u.post(f"/v1/manuscripts/{mid}/candidates/{cand['id']}/apply")
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_candidate"
    assert any(d["section"] == "introduction" for d in r.json()["error"]["details"]["diff_vs_current"])
    detail = (await u.get(f"/v1/manuscripts/{mid}/candidates/{cand['id']}")).json()
    assert detail["is_stale"] and detail["diff_vs_current"]

    # Explicit merge against the current version keeps the protected human sentence.
    r = await u.post(f"/v1/manuscripts/{mid}/candidates/{cand['id']}/merge",
                     json={"expected_version": 2, "take_candidate_sections": detail["sections"]})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 3 and r.json()["conflicts"][0]["section"] == "introduction"
    v3 = (await u.get(f"/v1/manuscripts/{mid}/versions/3")).json()
    kept = [s for s in spans(v3) if s["text"] == human]
    assert kept and kept[0]["origin"] == "human" and kept[0]["protected"]
    versions = (await u.get(f"/v1/manuscripts/{mid}/versions")).json()["items"]
    assert [v["origin"] for v in versions] == ["merge", "human_edit", "initial"]

    # Span provenance: factual spans cite registered claims/results; the bibliography derives from verified papers.
    lit_key, res_claim, rk = ids["literature"]["claim_key"], ids["result_claim"]["claim_key"], ids["result_key"]
    prior = [s for s in spans(v3) if s["kind"] == "prior_work" and s["claim_ids"]]
    observed = [s for s in spans(v3) if s["kind"] == "observed_result" and s["result_keys"]]
    assert prior and all(lit_key in s["claim_ids"] for s in prior)
    assert observed and all(rk in s["result_keys"] and not s["issues"] for s in observed)
    assert any(res_claim in s["claim_ids"] for s in observed)
    ms = (await u.get(f"/v1/projects/{pid}/manuscript")).json()
    bib = ms["bibliography"]
    assert len(bib) == 1 and "10.14778/3415478.3415556" in bib[0]["bibtex"]
    queue = ms["unresolved_claim_queue"]
    assert len(queue) == 1 and "most widely used" in queue[0]["text"]
    codes = {i["code"] for s in spans(v3) for i in s["issues"]}
    assert {"unsupported_factual_span", "gap_overstated"} <= codes
    assert ms["gap_argument_sections_present"] == {"abstract": True, "introduction": True, "discussion": True, "conclusion": True}

    proj = (await u.get(f"/v1/projects/{pid}")).json()
    r = await u.post(f"/v1/projects/{pid}/advance", json={"requested_state": "SCIENTIFIC_REVIEW", "expected_version": proj["version"]})
    assert r.status_code in (409, 422) and "blocking issues" in r.text

    # The author resolves the queue and the overstated sentence; the gate then passes.
    disc = section_payload(v3, "discussion")
    for p in disc["paragraphs"]:
        for sp in p["spans"]:
            if "fill" in sp["text"].lower() and "gap" in sp["text"].lower():
                sp["text"], sp["kind"] = "These results partly address the gap for R pipelines only.", "interpretation"
    rel = section_payload(v3, "related_work")
    for p in rel["paragraphs"]:
        p["spans"] = [sp for sp in p["spans"] if "most widely used" not in sp["text"]]
    r = await u.patch(f"/v1/manuscripts/{mid}", json={"expected_version": 3, "sections": [disc, rel],
                                                     "summary": "Removed unsupported claim; matched the gap assessment."})
    assert r.status_code == 200 and r.json()["checks"]["blockers"] == 0 and r.json()["checks"]["unresolved_claims"] == 0, r.text
    led = (await u.get(f"/v1/projects/{pid}/contribution-ledger")).json()["items"]
    assert sum(1 for e in led if e["source_action"] == "manuscript.edit") == 2
    assert any(e["source_action"] == "manuscript.merge" for e in led)

    # A fresh generation with no concurrent edit is applied directly.
    r = await u.post(f"/v1/projects/{pid}/drafts", json={"sections": ["conclusion"]})
    await run_all(u, temporal_env, pid)
    cand = next(c for c in (await u.get(f"/v1/projects/{pid}/manuscript")).json()["candidates"] if c["sections"] == ["conclusion"])
    assert cand["status"] == "ready"
    r = await u.post(f"/v1/manuscripts/{mid}/candidates/{cand['id']}/apply")
    assert r.status_code == 200 and r.json()["version"] == 5, r.text

    # Compile the committed version in the confirmed template (double-blind) inside the sandbox.
    await confirmed_acmart(u, temporal_env, pid)
    r = await u.post(f"/v1/projects/{pid}/compile", json={"anonymous": True})
    assert r.status_code == 202, r.text
    await run_all(u, temporal_env, pid)
    tpl = (await u.get(f"/v1/projects/{pid}/templates")).json()["items"][0]
    run = next(x for x in tpl["compile_runs"] if x["kind"] == "manuscript")
    checks = {c["id"]: c["status"] for c in run["checks"]}
    assert run["status"] == "compiled" and run["pages"] >= 1, run
    assert checks["anonymization.no_identity_leak"] == "passed" and checks["citations.resolved"] == "passed", checks
    assert run["manuscript_version_id"] == (await u.get(f"/v1/projects/{pid}/manuscript")).json()["manuscript"]["current_version"]["id"]

    proj = (await u.get(f"/v1/projects/{pid}")).json()
    r = await u.post(f"/v1/projects/{pid}/advance", json={"requested_state": "SCIENTIFIC_REVIEW", "expected_version": proj["version"]})
    assert r.status_code == 200, r.text

    # A changed result invalidates H3 and every manuscript span that cites it.
    import uuid

    from sqlalchemy import select as sa_select

    from rp_api.db.engine import session_scope
    from rp_api.db.models.contribution import ResultManifestRecord
    from rp_api.db.models.core import Project
    from rp_api.security.tokens import Principal
    from rp_api.services import invalidation

    async with session_scope("system") as db:
        project = (await db.execute(sa_select(Project).where(Project.id == uuid.UUID(pid)))).scalar_one()
        res = (await db.execute(sa_select(ResultManifestRecord).where(ResultManifestRecord.project_id == project.id))).scalar_one()
        actor = Principal(kind="service", subject="test", service_name="test-harness", tenant_id=project.tenant_id)
        out = await invalidation.invalidate(db, actor, project, [res.artifact_id], "result file corrected", f"test:{res.id}")
        await db.commit()
    assert {a["gate"] for a in out.invalidated_approvals} >= {"H3"} and out.reopened_to == "OUTCOME_REVIEW"
    assert any("manuscript spans citing changed results" in e for e in out.effects)
    cur = (await u.get(f"/v1/projects/{pid}/manuscript")).json()["manuscript"]["current_version"]
    stale = [s for s in cur["spans"] if rk in s["result_keys"]]
    assert stale and all(s["status"] == "stale" and any(i["code"] == "stale_result" for i in s["issues"]) for s in stale)
