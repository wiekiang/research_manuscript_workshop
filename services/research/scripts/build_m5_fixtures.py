"""Recorded methodology review for the M5 fixture protocol (contains one blocker so tests exercise resolution)."""

from __future__ import annotations

import json
from pathlib import Path

from rp_contracts.contribution import EthicsRightsDeclaration
from rp_contracts.hashing import canonical_json, sha256_hex
from rp_research.fixtures import m5_protocol as fx

ROOT = Path(__file__).resolve().parents[1] / "src" / "rp_research" / "fixtures" / "model" / "methodology_reviewer"


def main() -> None:
    content = {"method_definition": "empirical_quantitative@1", "sections": fx.SECTIONS,
               "ethics_rights": EthicsRightsDeclaration.model_validate(fx.ETHICS).model_dump(),
               "compute_estimate": fx.COMPUTE, "cost_estimate_cents": fx.COST_CENTS, "amendment": None, "version": 1}
    key = sha256_hex(canonical_json(content))
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / f"{key}.json").write_text(json.dumps({"fixture_for": "M5 tests", "output": {
        "can_answer_question": "partially",
        "issues": [
            {"severity": "blocker", "section": "sample_or_data_selection",
             "issue": "Eight pipelines cannot support a binomial test with meaningful power.",
             "rationale": "The planned exact test will be uninformative at n=8.",
             "proposed_fix": "Report the proportion with an interval and frame the study as exploratory, or enlarge the sample."},
            {"severity": "minor", "section": "operational_definitions", "issue": "Byte-identical may be too strict for timestamps.",
             "rationale": "Outputs embedding timestamps would never match.", "proposed_fix": "Normalise timestamps before comparing."},
        ],
        "threats_to_validity": ["selection bias in the curated list"], "ethics_flags": [], "cost_flags": []}}, indent=2) + "\n")
    print("review fixture", key[:12])


if __name__ == "__main__":
    main()
