"""CFP extractor and independent validator agents (PRODUCT_SPEC §2.2, §7)."""

from __future__ import annotations

import json
from typing import Any

from rp_contracts.cfp import CfpExtraction, CfpValidation
from rp_contracts.hashing import sha256_hex

from ..gateway import ModelCall
from ..gateway.core import wrap_untrusted
from .base import AgentSpec

RULE_KEYS = [
    "length.page_limit", "length.reference_pages", "abstract.word_limit", "format.layout", "template.family",
    "anonymization.mode", "supplementary.policy", "artifact.policy", "conflicts_of_interest.policy",
    "ethics.requirement", "prior_publication.policy", "dual_submission.policy", "preprint.policy",
    "ai_policy.statement", "ai_disclosure.location", "fees.statement", "submission_system.name",
    "citation_style.rule", "paper_types.allowed", "topics.list",
]

EXTRACT_SYSTEM = """You extract submission rules from an official conference call for papers (CFP).
Report only what the source states. Do not infer requirements, fill gaps from general knowledge of the venue, or
convert ambiguous statements into firm rules; put ambiguity in `uncertainty` instead.
For every rule and deadline give a short verbatim `quote` copied exactly from the source.
Use these rule keys when they fit (otherwise other.<short_slug>): {keys}.
Record every distinct deadline (abstract registration, full paper, supplementary, rebuttal, notification,
camera-ready, author registration, artifact) separately with the date as YYYY-MM-DD, the time if stated, and the
timezone exactly as written (null if none is stated - never assume one).
Set `track` to the track a rule belongs to, or null when it applies to the whole conference."""

VALIDATE_SYSTEM = """You independently check proposed CFP rules and deadlines against the official source text.
For each numbered item decide whether the source supports it exactly as stated (`supported`), contradicts or does
not contain it (`unsupported`), or is ambiguous about scope, value or timezone (`unclear`). Explain any issue.
Also list important requirements or deadlines in the source that the proposals missed. Do not trust the
proposals; read the source."""


def _scope_key(text: str) -> str:
    return sha256_hex(text.encode())


def build_extract_call(inputs: dict[str, Any]) -> ModelCall:
    text = inputs["source_text"]
    return ModelCall(
        agent="cfp_extractor", prompt_version="cfp-extract-1",
        system=EXTRACT_SYSTEM.format(keys=", ".join(RULE_KEYS)),
        user=f"Official source URL: {inputs.get('source_url') or 'researcher-supplied document'}\n\n"
             + wrap_untrusted(text, "cfp") + "\n\nExtract the edition, tracks, rules and deadlines.",
        output_model=CfpExtraction, data_classification="public", data_kinds=["cfp_documents"],
        input_artifact_ids=inputs.get("input_artifact_ids", []), max_tokens=16000,
        fixture_key=_scope_key(text))


def build_validate_call(inputs: dict[str, Any]) -> ModelCall:
    text = inputs["source_text"]
    items = inputs["items"]
    numbered = "\n".join(f"[{i['kind']} {i['index']}] {json.dumps(i['claim'], ensure_ascii=False)}" for i in items)
    return ModelCall(
        agent="cfp_validator", prompt_version="cfp-validate-1", system=VALIDATE_SYSTEM,
        user=wrap_untrusted(text, "cfp") + "\n\nProposed items to check:\n" + numbered,
        output_model=CfpValidation, data_classification="public", data_kinds=["cfp_documents"],
        input_artifact_ids=inputs.get("input_artifact_ids", []), max_tokens=12000,
        fixture_key=_scope_key(text))


EXTRACTOR = AgentSpec(name="cfp_extractor", prompt_version="cfp-extract-1", output_model=CfpExtraction,
                      build_call=build_extract_call)
VALIDATOR = AgentSpec(name="cfp_validator", prompt_version="cfp-validate-1", output_model=CfpValidation,
                      build_call=build_validate_call)
