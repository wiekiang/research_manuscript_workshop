"""Literature agents: evidence extraction, claim-support assessment and gap/opportunity proposals.

Post-validation is deterministic: quotes must occur verbatim in the provided text, referenced paper and passage
IDs must come from the provided inputs, and at least two proposals are required. Anything else is dropped and
reported, never silently accepted.
"""

from __future__ import annotations

import json
from typing import Any

from rp_contracts.hashing import sha256_hex
from rp_contracts.literature import EvidenceExtraction, OpportunitySet, SupportAssessment
from rp_contracts.textmatch import find_span

from ..gateway import ModelCall
from ..gateway.core import wrap_untrusted
from .base import AgentSpec

EXTRACT_SYSTEM = """You extract evidence from one scholarly paper for a researcher.
Copy each passage verbatim (one to three sentences) from the paper text. Record methods, population or dataset,
results and limitations only as the paper states them. List distinct claims the paper makes, each linked to the
passages that state it. Do not add knowledge from outside the text, do not generalise beyond what is stated, and do
not convert hedged statements into firm ones."""

SUPPORT_SYSTEM = """You assess whether an evidence passage supports a stated claim, as a model-assisted check that a
human may review. Judge only the relationship between the claim and the passage. Mark strength_mismatch when the
claim is stronger than the passage (causal language for correlational evidence, broader population or scope,
different or more precise numbers)."""

OPP_SYSTEM = """You propose candidate research directions for a researcher, as advisory input to their own decision.
Use only the provided papers and passages. For each proposal name the nearest prior work by the provided paper IDs,
state concretely how the proposal differs, and keep novelty a hypothesis (give a caveat). Ground the gap in provided
passage IDs where possible; never invent citations or evidence. Recommend study types (from the provided list) and
venue submission categories as separate choices. Time estimates are rough ranges. Propose at least two directions,
and report negative findings (angles where prior work already covers the gap)."""


def build_extract(inputs: dict[str, Any]) -> ModelCall:
    text = inputs["text"]
    return ModelCall(agent="evidence_extractor", prompt_version="evidence-extract-1", system=EXTRACT_SYSTEM,
                     user=f"Paper: {inputs.get('title')}\n\n" + wrap_untrusted(text[:180000], "paper"),
                     output_model=EvidenceExtraction, data_classification="internal", data_kinds=["uploaded_papers"],
                     input_artifact_ids=inputs.get("input_artifact_ids", []), max_tokens=12000,
                     fixture_key=sha256_hex(text.encode()))


def validate_extract(inputs: dict[str, Any], out: EvidenceExtraction) -> tuple[dict, list[str]]:
    text = inputs["text"]
    keep, problems = [], []
    index_map = {}
    for i, p in enumerate(out.passages):
        if find_span(text, p.quote) is None:
            problems.append(f"passage {i} dropped: quote not found verbatim")
            continue
        index_map[i] = len(keep)
        keep.append(p)
    claims = []
    for c in out.claims:
        idx = [index_map[i] for i in c.passage_indices if i in index_map]
        if not idx:
            problems.append(f"claim dropped (no verified passage): {c.proposition[:80]}")
            continue
        claims.append(c.model_copy(update={"passage_indices": idx}))
    data = out.model_copy(update={"passages": keep, "claims": claims}).model_dump(mode="json")
    return data, problems


def build_support(inputs: dict[str, Any]) -> ModelCall:
    payload = f"Claim: {inputs['claim']}\n\nPassage (from {inputs.get('paper_title')}):\n" + wrap_untrusted(inputs["quote"], "passage")
    return ModelCall(agent="support_assessor", prompt_version="support-assess-1", system=SUPPORT_SYSTEM, user=payload,
                     output_model=SupportAssessment, data_classification="internal", data_kinds=["uploaded_papers"],
                     max_tokens=4000, fixture_key=sha256_hex((inputs["claim"] + "||" + inputs["quote"]).encode()))


def opportunity_fixture_key(inputs: dict[str, Any]) -> str:
    basis = {"topic": inputs["project"].get("topic"), "papers": sorted((p.get("doi") or p["title"]).lower() for p in inputs["papers"])}
    return sha256_hex(json.dumps(basis, sort_keys=True).encode())


def build_opportunity(inputs: dict[str, Any]) -> ModelCall:
    papers = "\n".join(f"- [{p['id']}] {p['title']} ({p.get('year') or 'n.d.'}; {p.get('venue') or ''})"
                       + (f"\n  abstract: {p['abstract'][:1200]}" if p.get("abstract") else "") for p in inputs["papers"])
    passages = "\n".join(f"- [{x['id']}] ({x['role']}) {x['quote']}" for x in inputs["passages"])
    cfp = inputs.get("cfp") or {}
    body = (f"Project: {inputs['project'].get('title')}\nTopic: {inputs['project'].get('topic')}\n"
            f"CFP topics: {cfp.get('topics') or 'not available'}\nTracks: {json.dumps(cfp.get('tracks') or [])}\n"
            f"Study types: {json.dumps(inputs['study_types'])}\nVenue categories: {inputs['venue_categories']}\n\n"
            + wrap_untrusted(f"Papers:\n{papers}\n\nVerified passages:\n{passages or 'none'}", "literature"))
    return ModelCall(agent="opportunity_generator", prompt_version="opportunity-1", system=OPP_SYSTEM, user=body,
                     output_model=OpportunitySet, data_classification="internal", data_kinds=["uploaded_papers"],
                     max_tokens=16000, fixture_key=opportunity_fixture_key(inputs))


def validate_opportunity(inputs: dict[str, Any], out: OpportunitySet) -> tuple[dict, list[str]]:
    paper_ids = {p["id"] for p in inputs["papers"]}
    passage_ids = {x["id"] for x in inputs["passages"]}
    problems = []
    props = []
    for i, p in enumerate(out.proposals, start=1):
        bad_papers = [x for x in p.closest_work_paper_ids if x not in paper_ids]
        bad_pass = [x for x in p.rationale.gap_evidence_passage_ids if x not in passage_ids]
        if bad_papers or bad_pass:
            problems.append(f"proposal {i}: removed references not in the inputs ({len(bad_papers) + len(bad_pass)})")
        props.append(p.model_copy(update={
            "closest_work_paper_ids": [x for x in p.closest_work_paper_ids if x in paper_ids],
            "rationale": p.rationale.model_copy(update={
                "gap_evidence_passage_ids": [x for x in p.rationale.gap_evidence_passage_ids if x in passage_ids]})}))
    if len(props) < 2:
        problems.append("fewer than two proposals were produced")
    return out.model_copy(update={"proposals": props}).model_dump(mode="json"), problems


EXTRACTOR = AgentSpec("evidence_extractor", "evidence-extract-1", EvidenceExtraction, build_extract, validate_extract)
SUPPORT = AgentSpec("support_assessor", "support-assess-1", SupportAssessment, build_support)
OPPORTUNITY = AgentSpec("opportunity_generator", "opportunity-1", OpportunitySet, build_opportunity, validate_opportunity)
