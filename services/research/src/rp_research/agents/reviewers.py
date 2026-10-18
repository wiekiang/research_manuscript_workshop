"""Independent review agents (PRODUCT_SPEC §2.11).

The scientific reviewer sees the manuscript, approved protocol, H3 matrix and underlying claims/results. The meaning
checker sees one claim, the evidence the citation reviewer opened itself, and the linked spans. Neither sees another
reviewer's report. Post-validation removes span/claim IDs that were not in the inputs.
"""

from __future__ import annotations

import json
from typing import Any

from rp_contracts.hashing import canonical_json, sha256_hex
from rp_contracts.review import MeaningCheckOutput, ScientificReviewOutput

from ..gateway import ModelCall
from ..gateway.core import wrap_untrusted
from .base import AgentSpec

SCI_SYSTEM = """You are an independent scientific and methodological reviewer of a manuscript draft. Assess the research
question, the approved protocol, the evidence, the claimed contribution and the conclusions. Report concrete findings
with severity (blocker, major, minor, suggestion), the span or claim IDs they concern, a rationale, a reproducible
check and a proposed fix. Judge the conclusions against the evidence and the H3 interpretation; flag generalisation
beyond the sample, overstated contribution and missing limitations. Do not score the paper and do not predict
acceptance; your review is diagnostic."""

MEANING_SYSTEM = """You check whether each manuscript span faithfully represents a claim and the evidence behind it.
The evidence was opened directly from the stored source by the citation reviewer. For every span return a verdict:
faithful, scope_drift (broader or different population/setting), strength_overstated (stronger than the evidence,
e.g. causal for correlational, certain for hedged), unsupported, or contradicted. Give a short rationale and, when not
faithful, suggested wording that stays within the evidence."""


def scientific_fixture_key(inputs: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({"content": inputs["content_digest"], "protocol": (inputs.get("protocol") or {}).get("hash")}))


def build_scientific(inputs: dict[str, Any]) -> ModelCall:
    spans = "\n".join(f"[{s['span_id']}] ({s['section']}/{s['kind']}; claims={s['claim_ids']}; results={s['result_keys']}) "
                      f"{s['text']}" for s in inputs["spans"])
    body = ("Manuscript spans:\n" + wrap_untrusted(spans, "manuscript") + "\n\nApproved protocol:\n"
            + wrap_untrusted(json.dumps(inputs.get("protocol"), indent=1), "protocol") + "\n\nH3 contribution matrix:\n"
            + wrap_untrusted(json.dumps(inputs.get("matrix"), indent=1), "matrix") + "\n\nClaims:\n"
            + wrap_untrusted(json.dumps(inputs["claims"], indent=1), "claims") + "\n\nResults:\n"
            + wrap_untrusted(json.dumps(inputs["results"], indent=1), "results"))
    return ModelCall(agent="scientific_reviewer", prompt_version="sci-review-1", system=SCI_SYSTEM, user=body,
                     output_model=ScientificReviewOutput, data_classification="internal",
                     data_kinds=["unpublished_manuscript"], input_artifact_ids=[inputs["manuscript_artifact_id"]],
                     max_tokens=12000, fixture_key=scientific_fixture_key(inputs))


def validate_scientific(inputs: dict[str, Any], out: ScientificReviewOutput) -> tuple[dict, list[str]]:
    spans = {s["span_id"] for s in inputs["spans"]}
    claims = {c["key"] for c in inputs["claims"]}
    problems, fs = [], []
    for f in out.findings:
        bad = [x for x in f.span_ids if x not in spans] + [x for x in f.claim_ids if x not in claims]
        if bad:
            problems.append(f"removed IDs not in the inputs: {bad}")
        fs.append(f.model_copy(update={"span_ids": [x for x in f.span_ids if x in spans],
                                       "claim_ids": [x for x in f.claim_ids if x in claims]}))
    return out.model_copy(update={"findings": fs}).model_dump(mode="json"), problems


def meaning_fixture_key(inputs: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({"claim": inputs["proposition"], "evidence": inputs["evidence_text"],
                                      "spans": sorted((s["span_id"], s["text"]) for s in inputs["spans"])}))


def build_meaning(inputs: dict[str, Any]) -> ModelCall:
    spans = "\n".join(f"[{s['span_id']}] {s['text']}" for s in inputs["spans"])
    body = (f"Claim {inputs['key']}: {inputs['proposition']}\n\nEvidence (opened from the stored source):\n"
            + wrap_untrusted(inputs["evidence_text"], "evidence") + "\n\nManuscript spans citing this claim:\n"
            + wrap_untrusted(spans, "manuscript"))
    return ModelCall(agent="meaning_checker", prompt_version="meaning-check-1", system=MEANING_SYSTEM, user=body,
                     output_model=MeaningCheckOutput, data_classification="internal",
                     data_kinds=["unpublished_manuscript", "uploaded_papers"], max_tokens=4000,
                     fixture_key=meaning_fixture_key(inputs))


def validate_meaning(inputs: dict[str, Any], out: MeaningCheckOutput) -> tuple[dict, list[str]]:
    ids = {s["span_id"] for s in inputs["spans"]}
    got = [s for s in out.spans if s.span_id in ids]
    problems = [f"verdict for unknown span {s.span_id} dropped" for s in out.spans if s.span_id not in ids]
    missing = ids - {s.span_id for s in got}
    if missing:
        problems.append(f"no verdict for spans {sorted(missing)}")
    return out.model_copy(update={"spans": got}).model_dump(mode="json"), problems


SCIENTIFIC = AgentSpec("scientific_reviewer", "sci-review-1", ScientificReviewOutput, build_scientific, validate_scientific)
MEANING = AgentSpec("meaning_checker", "meaning-check-1", MeaningCheckOutput, build_meaning, validate_meaning)
