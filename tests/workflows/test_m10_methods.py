"""M10 acceptance: method-specific validation for evidence synthesis and qualitative research.

Meta-analysis path: the review specification is frozen with the protocol; every specified search runs exactly as
written; screening is human with protocol reasons; extraction links values to verified passages; the platform pools
deterministically (benchmark with hand-derived values) and a stale synthesis cannot validate; the appendix
reconciles with stored records. Qualitative path: ethics approval recorded, verbatim source-to-code trace,
themes traced to coded segments. Neither path needs a paid provider subscription."""

from __future__ import annotations

import json
import math

import pytest
from test_m4_literature import KNOWN_DOI, providers, upload_known_paper  # noqa: F401
from test_m5_contribution import contribute, decl, h1, open_cfp, project_at_direction_review, select  # noqa: F401
from test_m6_manuscript import run_all

from rp_research.fixtures import m5_protocol as fx

pytestmark = pytest.mark.temporal

SPEC = {
    "review_type": "meta_analysis",
    "question": "How often does recording library versions restore pipeline outputs across studies?",
    "searches": [{"provider": "crossref", "query": "provenance reproducibility data pipelines", "year_from": 2015,
                  "max_results": 25}],
    "inclusion_criteria": ["empirical study of re-executing data pipelines", "reports a restoration outcome"],
    "exclusion_reasons": ["not an empirical study", "no restoration outcome reported", "duplicate publication"],
    "extraction_form": [{"key": "population", "label": "Pipelines studied"},
                        {"key": "outcome", "label": "Restoration outcome"}],
    "appraisal_tool": "Adapted ROBINS-I (selection domain)",
    "appraisal_items": [{"key": "selection_bias", "label": "Bias in selection of pipelines"}],
    "synthesis": "meta_analysis", "effect_measure": "log odds of restoration", "pooling_model": "random_dl",
    "reporting_standard": "PRISMA 2020",
}


async def protocol_and_h2(u, env, pid, sections, ethics):
    r = await u.post(f"/v1/projects/{pid}/protocols", json={"sections": sections, "ethics_rights": ethics,
                                                           "compute_estimate": "minimal", "cost_estimate_cents": 0})
    assert r.status_code == 201, r.text
    assert r.json()["validation"]["missing_sections"] == [], r.json()["validation"]
    v = r.json()["version"]
    await u.post(f"/v1/projects/{pid}/protocols/{v}/waive-review", json={
        "rationale": "Reviewed by a methodologist colleague offline against the reporting standard."})
    r = await u.post(f"/v1/projects/{pid}/protocols/{v}/approve", json={"declaration_accepted": True,
                                                                      "declaration_text": await decl(u, pid, "H2")})
    assert r.status_code == 200 and r.json()["transition"]["state"] == "RESEARCH_ACTIVE", r.text


async def stage(u, pid, sid, **body):
    r = await u.post(f"/v1/projects/{pid}/method-stages/{sid}", json={"description": "", **body})
    assert r.status_code == 201, r.text
    return r.json()


async def test_meta_analysis_validated_end_to_end(client, temporal_env, open_cfp):  # noqa: F811
    u, pid, opp = await project_at_direction_review(client, temporal_env)
    assert (await select(u, pid, "meta_analysis", opp)).status_code == 201
    assert (await h1(u, pid, opp)).status_code == 200
    bad = {**fx.SECTIONS, "review_specification": json.dumps({**SPEC, "pooling_model": None})}
    r = await u.post(f"/v1/projects/{pid}/protocols", json={"sections": bad, "ethics_rights": fx.ETHICS,
                                                           "compute_estimate": "minimal", "cost_estimate_cents": 0})
    assert any("pooling model" in m for m in r.json()["validation"]["missing_sections"]), r.json()
    await protocol_and_h2(u, temporal_env, pid, {**fx.SECTIONS, "review_specification": json.dumps(SPEC)}, fx.ETHICS)
    assert (await stage(u, pid, "frozen_protocol"))["status"] == "validated"

    s = await stage(u, pid, "search")
    assert s["status"] == "failed" and "not executed exactly as specified" in s["validators"][0]["detail"]
    r = await u.post(f"/v1/projects/{pid}/review/searches")
    assert r.status_code == 202 and r.json()["runs"][0]["query"] == SPEC["searches"][0]["query"]
    await run_all(u, temporal_env, pid)
    assert (await stage(u, pid, "search"))["status"] == "validated"

    ws = (await u.get(f"/v1/projects/{pid}/review")).json()
    recs = {x["doi"]: x for x in ws["records"]}
    assert ws["flow"]["identified"] == 5 and ws["flow"]["screened"] == len(recs) == 5
    s = await stage(u, pid, "screening")
    assert s["status"] == "failed" and "no title/abstract decision" in s["validators"][0]["detail"]
    included = [KNOWN_DOI, "10.1007/978-3-030-80960-7_17", "10.2139/ssrn.7323260"]
    r = await u.post(f"/v1/projects/{pid}/review/screening", json={
        "paper_id": recs["10.18122/td.2050.boisestate"]["paper_id"], "stage": "title_abstract", "decision": "exclude",
        "reason": "looked boring"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_not_in_protocol"
    for doi, rec in recs.items():
        inc = doi in included
        body = {"paper_id": rec["paper_id"], "stage": "title_abstract", "decision": "include" if inc else "exclude",
                "reason": None if inc else "not an empirical study"}
        assert (await u.post(f"/v1/projects/{pid}/review/screening", json=body)).status_code == 201
        if inc:
            assert (await u.post(f"/v1/projects/{pid}/review/screening", json={**body, "stage": "full_text"})).status_code == 201
    assert (await stage(u, pid, "screening"))["status"] == "validated"

    # Extraction: values link to verified passages (or are marked not reported); appraisal per protocol item.
    await upload_known_paper(u, pid)
    await run_all(u, temporal_env, pid)
    known_id = recs[KNOWN_DOI]["paper_id"]
    passage = next(p for p in (await u.get(f"/v1/projects/{pid}/evidence")).json()["passages"] if p["paper_id"] == known_id)
    r = await u.post(f"/v1/projects/{pid}/review/extractions", json={
        "paper_id": known_id, "values": {"outcome": {"value": "7 of 8 restored"}}})
    assert r.status_code == 422 and "verified passage" in str(r.json())
    effects = {KNOWN_DOI: 0.1, "10.1007/978-3-030-80960-7_17": 0.5, "10.2139/ssrn.7323260": 0.9}
    for doi in included:
        values = {"population": {"not_reported": True},
                  "outcome": {"value": "7 of 8 restored", "passage_id": passage["id"]} if doi == KNOWN_DOI else {"not_reported": True}}
        r = await u.post(f"/v1/projects/{pid}/review/extractions", json={
            "paper_id": recs[doi]["paper_id"], "values": values,
            "appraisal": {"selection_bias": {"rating": "some_concerns", "rationale": "curated convenience sample"}},
            "effect": {"estimate": effects[doi], "variance": 0.01}})
        assert r.status_code == 201, r.text
    assert (await stage(u, pid, "extraction"))["status"] == "validated"

    s = await stage(u, pid, "pooling")
    assert s["status"] == "failed" and "run the synthesis" in s["validators"][0]["detail"]
    syn = (await u.post(f"/v1/projects/{pid}/review/synthesis")).json()["meta_analysis"]
    # Benchmark (hand-derived): y=(0.1,0.5,0.9), v=0.01 -> w=100 each, FE=0.5, Q=32, df=2, C=200, tau2=(32-2)/200=0.15,
    # I2=(32-2)/32=93.75%, RE weights 1/0.16=6.25 -> estimate 0.5, se=sqrt(1/18.75).
    assert syn["k"] == 3 and math.isclose(syn["estimate"], 0.5, abs_tol=1e-12) and math.isclose(syn["q"], 32, rel_tol=1e-12)
    assert math.isclose(syn["tau2"], 0.15, rel_tol=1e-12) and math.isclose(syn["i2"], 93.75, rel_tol=1e-12)
    assert math.isclose(syn["se"], math.sqrt(1 / 18.75), rel_tol=1e-12)
    s = await stage(u, pid, "pooling")
    assert s["status"] == "validated" and "recomputed" in s["validators"][0]["detail"]
    assert s["transition"]["state"] == "OUTCOME_REVIEW"

    app = (await u.post(f"/v1/projects/{pid}/review/appendix")).json()
    assert app["searches"][0]["query"] == SPEC["searches"][0]["query"] and app["searches"][0]["executed_at"]
    assert app["flow"]["included"] == 3 and app["flow"]["screened_out"] == 2
    assert all(v["reason"] == "not an empirical study" for v in app["screening"]["title_abstract"].values()
               if v["decision"] == "exclude")
    assert app["synthesis"]["meta_analysis"]["engine"] == "rp-synthesis/1"

    # A changed extraction makes the stored synthesis stale; the stage cannot validate until it is recomputed.
    await u.post(f"/v1/projects/{pid}/review/extractions", json={
        "paper_id": recs[KNOWN_DOI]["paper_id"], "values": {"population": {"not_reported": True}, "outcome": {"not_reported": True}},
        "appraisal": {"selection_bias": {"rating": "high", "rationale": "single curated sample"}},
        "effect": {"estimate": 0.2, "variance": 0.01}})
    s = await stage(u, pid, "pooling")
    assert s["status"] == "failed" and "not current" in s["validators"][0]["detail"]


QUAL_ETHICS = {"involves_human_participants": True, "personal_data": True, "sensitive_data": False,
               "restricted_datasets": False, "data_licences": [],
               "institutional_approval": {"required": True, "status": "obtained", "body": "Example University IRB",
                                          "reference": "IRB-2026-0142"},
               "consent_procedure": "Written informed consent before each interview.",
               "deidentification_plan": "Names and employers removed before analysis; key held separately.",
               "declaration_text_accepted": True}
TRANSCRIPT = (b"Interviewer: How do you handle package upgrades?\n"
              b"P1: Honestly we pin everything in a lockfile, because last year an upgrade silently changed our results.\n"
              b"P1: Nobody noticed for weeks until a reviewer asked us to rerun the analysis.\n")


async def test_qualitative_source_to_code_trace(client, temporal_env, open_cfp):  # noqa: F811
    u, pid, opp = await project_at_direction_review(client, temporal_env)
    assert (await select(u, pid, "empirical_qualitative", opp)).status_code == 201
    assert (await h1(u, pid, opp)).status_code == 200
    await protocol_and_h2(u, temporal_env, pid, fx.SECTIONS, QUAL_ETHICS)
    assert (await stage(u, pid, "ethics_rights"))["status"] == "validated"
    t = await contribute(u, pid, "interview-p1.txt", TRANSCRIPT, ctype="observations")
    assert (await stage(u, pid, "collection", description="Two semi-structured interviews, transcribed verbatim and "
                                                           "de-identified before analysis under the approved protocol.",
                        contribution_ids=[t["id"]]))["status"] == "validated"
    code = (await u.post(f"/v1/projects/{pid}/qual/codes", json={
        "code": "defensive pinning", "definition": "Pinning dependencies after a bad upgrade experience."})).json()
    s = await stage(u, pid, "coding")
    assert s["status"] == "failed" and "no coded segment" in s["validators"][0]["detail"]
    r = await u.post(f"/v1/projects/{pid}/qual/segments", json={"code_id": code["id"], "contribution_id": t["id"],
                                                               "quote": "we never upgrade anything ever again"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "quote_not_in_source"
    r = await u.post(f"/v1/projects/{pid}/qual/segments", json={
        "code_id": code["id"], "contribution_id": t["id"],
        "quote": "we pin everything in a lockfile, because last year an upgrade silently changed our results"})
    assert r.status_code == 201 and r.json()["verified"]
    assert (await stage(u, pid, "coding"))["status"] == "validated"
    s = await stage(u, pid, "analysis")
    assert s["status"] == "failed" and "no themes" in s["validators"][0]["detail"]
    await u.post(f"/v1/projects/{pid}/qual/themes", json={
        "name": "Pinning as institutional memory", "description": "Teams pin after an incident rather than by policy.",
        "code_ids": [code["id"]],
        "interpretation": "Participants framed lockfiles as a reaction to a past silent change, suggesting that version "
                          "recording is adopted after harm rather than proactively; this is my reading of two interviews."})
    s = await stage(u, pid, "analysis")
    assert s["status"] == "validated" and s["transition"]["state"] == "OUTCOME_REVIEW", s


async def screened(client, env, study_type, spec):
    """Shared path: H1, frozen spec, executed searches, human screening (3 included, 2 excluded with reasons)."""
    u, pid, opp = await project_at_direction_review(client, env)
    assert (await select(u, pid, study_type, opp)).status_code == 201
    assert (await h1(u, pid, opp)).status_code == 200
    await protocol_and_h2(u, env, pid, {**fx.SECTIONS, "review_specification": json.dumps(spec)}, fx.ETHICS)
    assert (await stage(u, pid, "frozen_protocol"))["status"] == "validated"
    await u.post(f"/v1/projects/{pid}/review/searches")
    await run_all(u, env, pid)
    assert (await stage(u, pid, "search"))["status"] == "validated"
    recs = {x["doi"]: x for x in (await u.get(f"/v1/projects/{pid}/review")).json()["records"]}
    included = [KNOWN_DOI, "10.1007/978-3-030-80960-7_17", "10.2139/ssrn.7323260"]
    for doi, rec in recs.items():
        inc = doi in included
        body = {"paper_id": rec["paper_id"], "stage": "title_abstract", "decision": "include" if inc else "exclude",
                "reason": None if inc else spec["exclusion_reasons"][0]}
        await u.post(f"/v1/projects/{pid}/review/screening", json=body)
        if inc:
            await u.post(f"/v1/projects/{pid}/review/screening", json={**body, "stage": "full_text"})
    assert (await stage(u, pid, "screening"))["status"] == "validated"
    return u, pid, {d: recs[d]["paper_id"] for d in included}


MAP_SPEC = {**{k: SPEC[k] for k in ("question", "searches", "inclusion_criteria", "exclusion_reasons")},
            "review_type": "mapping_review", "synthesis": "map", "reporting_standard": "Petersen et al. (2015)",
            "charting_scheme": [{"key": "method", "label": "Research method", "categories": ["experiment", "case_study", "survey"]},
                                {"key": "ecosystem", "label": "Ecosystem", "categories": ["python", "r", "mixed"]}]}


async def test_mapping_review_charting_map(client, temporal_env, open_cfp):  # noqa: F811
    u, pid, ids = await screened(client, temporal_env, "mapping_review", MAP_SPEC)
    rows = [("experiment", "python"), ("case_study", "mixed"), ("experiment", "r")]
    r = await u.post(f"/v1/projects/{pid}/review/extractions", json={"paper_id": ids[KNOWN_DOI],
                                                                    "charting": {"method": "experiment"}})
    assert r.status_code == 201
    s = await stage(u, pid, "charting")
    assert s["status"] == "failed" and "charting 'ecosystem' missing" in s["validators"][0]["detail"]
    for (m, e), pid_ in zip(rows, ids.values(), strict=True):
        assert (await u.post(f"/v1/projects/{pid}/review/extractions", json={
            "paper_id": pid_, "charting": {"method": m, "ecosystem": e}})).status_code == 201
    assert (await stage(u, pid, "charting"))["status"] == "validated"
    syn = (await u.post(f"/v1/projects/{pid}/review/synthesis")).json()["map"]
    assert syn["dimensions"]["method"] == {"experiment": 2, "case_study": 1, "survey": 0} and not syn["problems"]
    s = await stage(u, pid, "map")
    assert s["status"] == "validated" and s["transition"]["state"] == "OUTCOME_REVIEW"


TERT_SPEC = {**{k: SPEC[k] for k in ("question", "searches", "inclusion_criteria", "exclusion_reasons")},
             "review_type": "tertiary_review", "synthesis": "review_of_reviews", "reporting_standard": "PRIOR",
             "appraisal_tool": "AMSTAR 2 (selected items)",
             "appraisal_items": [{"key": "protocol_registered", "label": "Protocol registered before the review",
                                  "ratings": ["yes", "partial", "no"]}]}


async def test_tertiary_review_overlap(client, temporal_env, open_cfp):  # noqa: F811
    u, pid, ids = await screened(client, temporal_env, "tertiary_review", TERT_SPEC)
    primaries = [["p1", "p2"], ["p2", "p3"], ["p1", "p4"]]
    for prim, pid_ in zip(primaries, ids.values(), strict=True):
        assert (await u.post(f"/v1/projects/{pid}/review/extractions", json={
            "paper_id": pid_, "primary_studies": prim,
            "appraisal": {"protocol_registered": {"rating": "partial", "rationale": "protocol described, not registered"}}}
        )).status_code == 201
    assert (await stage(u, pid, "appraisal_extraction"))["status"] == "validated"
    s = await stage(u, pid, "synthesis", description="x" * 50)
    assert s["status"] == "failed"
    ov = (await u.post(f"/v1/projects/{pid}/review/synthesis")).json()["overlap"]
    assert math.isclose(ov["cca"], 0.25) and ov["level"] == "very high"
    narrative = ("The three included reviews overlap heavily in their primary studies (CCA 0.25), so their agreement is "
                 "partly the same evidence counted repeatedly. Conclusions about version recording should therefore be "
                 "weighted by unique primary studies rather than by the number of reviews.")
    s = await stage(u, pid, "synthesis", description=narrative)
    assert s["status"] == "validated" and s["transition"]["state"] == "OUTCOME_REVIEW", s


async def test_scoping_review_charting_and_map(client, temporal_env, open_cfp):  # noqa: F811
    spec = {**MAP_SPEC, "review_type": "scoping_review", "reporting_standard": "PRISMA-ScR"}
    u, pid, ids = await screened(client, temporal_env, "scoping_review", spec)
    for pid_ in ids.values():
        assert (await u.post(f"/v1/projects/{pid}/review/extractions", json={
            "paper_id": pid_, "charting": {"method": "survey", "ecosystem": "mixed"}})).status_code == 201
    assert (await stage(u, pid, "charting"))["status"] == "validated"
    syn = (await u.post(f"/v1/projects/{pid}/review/synthesis")).json()["map"]
    assert syn["dimensions"]["ecosystem"]["mixed"] == 3
    s = await stage(u, pid, "map")
    assert s["status"] == "validated" and s["transition"]["state"] == "OUTCOME_REVIEW"
