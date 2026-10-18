"""Section writer agent (PRODUCT_SPEC §2.10).

The writer receives only the frozen brief: verified claim keys with their propositions, committed result keys with
metrics, assurance level and wording limits, the H3 matrix and the researcher's gap assessment. It returns
sentence-level spans that declare their kind and cite claim/result keys. Post-validation removes any key that was not
in the inputs (and reports it); the API then re-checks every span deterministically. The writer cannot add
bibliography entries: citations are derived from the papers that support each cited claim.
"""

from __future__ import annotations

import json
from typing import Any

from rp_contracts.hashing import canonical_json, sha256_hex
from rp_contracts.manuscript import SectionDraft

from ..gateway import ModelCall
from ..gateway.core import wrap_untrusted
from .base import AgentSpec

WRITER_SYSTEM = """You draft one section of a scholarly manuscript for the researcher, who will review and edit it.
Write sentence-level spans. Give every span a kind: prior_work, observed_result, method, interpretation, hypothesis,
limitation, contribution_statement or framing. A prior_work span must cite at least one provided claim key; an
observed_result span must cite the provided result keys (and may cite claim keys). Use only numbers that appear in the
cited results or claims. Respect each result's wording limits and assurance level. Never invent citations, results,
datasets, approvals or contributors. Do not say the gap was filled or closed unless the gap assessment is
'addressed'; in proposal mode describe planned analyses only and report no observed results. Label interpretation,
hypotheses and limitations as such. Use tables only by listing result keys; the system renders values itself."""

PROMPT_VERSION = "section-writer-1"


def writer_signature(inputs: dict[str, Any]) -> dict[str, Any]:
    b = inputs["brief"]
    return {"section": inputs["section"]["key"], "mode": b["mode"], "rq": b.get("research_question"),
            "claims": sorted((c["key"], c["proposition"]) for c in b["claims"]),
            "results": sorted(r["key"] for r in b["results"]),
            "gap": (b.get("matrix") or {}).get("gap_resolution", {}).get("status") if b.get("matrix") else None,
            "instructions": inputs.get("instructions")}


def writer_fixture_key(inputs: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(writer_signature(inputs)))


def build_writer(inputs: dict[str, Any]) -> ModelCall:
    b = inputs["brief"]
    sec = inputs["section"]
    claims = "\n".join(f"- {c['key']} ({c['kind']}/{c['category']}): {c['proposition']}" for c in b["claims"]) or "none"
    results = "\n".join(f"- {r['key']} {r['title']} [assurance: {r['assurance']}] metrics={json.dumps(r['metrics'])}"
                        f" wording_limits={r['wording_limits']}" for r in b["results"]) or "none"
    matrix = json.dumps(b.get("matrix"), indent=1) if b.get("matrix") else "not available (proposal mode)"
    body = (f"Section to write: {sec['heading']} (key {sec['key']})\nMode: {b['mode']}\nStudy type: {b.get('study_type')}\n"
            f"Title: {b['title']}\nResearch question: {b.get('research_question')}\n"
            f"Intended contribution: {b.get('intended_contribution')}\nHow it differs: {b.get('how_it_differs')}\n"
            f"Novelty caveat: {b.get('novelty_caveat')}\nVenue rules: {json.dumps(b.get('rules'))}\n"
            f"Writing rules: {json.dumps(b.get('writing_rules'))}\n"
            f"Researcher instructions: {inputs.get('instructions') or 'none'}\n\n"
            + wrap_untrusted(f"Verified claims:\n{claims}\n\nCommitted results:\n{results}\n\nContribution matrix:\n{matrix}\n\n"
                             f"Protocol (frozen): {json.dumps((b.get('protocol') or {}).get('sections'), indent=1)}", "brief"))
    return ModelCall(agent="section_writer", prompt_version=PROMPT_VERSION, system=WRITER_SYSTEM, user=body,
                     output_model=SectionDraft, data_classification="internal",
                     data_kinds=["unpublished_manuscript"], input_artifact_ids=inputs.get("input_artifact_ids", []),
                     max_tokens=12000, fixture_key=writer_fixture_key(inputs))


def validate_writer(inputs: dict[str, Any], out: SectionDraft) -> tuple[dict, list[str]]:
    b = inputs["brief"]
    claim_keys = {c["key"] for c in b["claims"]}
    result_keys = {r["key"] for r in b["results"]}
    problems: list[str] = []
    if out.key != inputs["section"]["key"]:
        problems.append(f"writer returned section {out.key}; expected {inputs['section']['key']}")
    paras = []
    for p in out.paragraphs:
        spans = []
        for sp in p.spans:
            bad = [k for k in sp.claim_ids if k not in claim_keys] + [k for k in sp.result_keys if k not in result_keys]
            if bad:
                problems.append(f"removed references not in the brief: {bad}")
            spans.append(sp.model_copy(update={"claim_ids": [k for k in sp.claim_ids if k in claim_keys],
                                               "result_keys": [k for k in sp.result_keys if k in result_keys]}))
        if spans:
            paras.append(p.model_copy(update={"spans": spans}))
    tables = [t.model_copy(update={"result_keys": [k for k in t.result_keys if k in result_keys]})
              for t in out.tables if any(k in result_keys for k in t.result_keys)]
    data = out.model_copy(update={"key": inputs["section"]["key"], "heading": inputs["section"]["heading"],
                                  "paragraphs": paras, "tables": tables}).model_dump(mode="json")
    return data, problems


WRITER = AgentSpec("section_writer", PROMPT_VERSION, SectionDraft, build_writer, validate_writer)
