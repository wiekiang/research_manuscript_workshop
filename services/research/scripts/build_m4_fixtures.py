"""Recorded fixture-model responses for the M4 evidence pipeline tests (synthetic, test/demo only).

The extraction recording contains one fabricated quote (absent from the text) so tests prove it is dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

from rp_contracts.hashing import sha256_hex
from rp_research.agents.literature import opportunity_fixture_key
from rp_research.fetch.text import extract_plain

ROOT = Path(__file__).resolve().parents[1] / "src" / "rp_research" / "fixtures"
CLAIM = "Recording library versions restored most pipelines whose outputs changed after re-execution."
QUOTE = "Recording library versions allowed seven of those eight pipelines to be restored to their original outputs."


def write(agent: str, key: str, out: dict) -> None:
    d = ROOT / "model" / agent
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.json").write_text(json.dumps({"fixture_for": "M4 tests", "output": out}, indent=2) + "\n")


def main() -> None:
    text = extract_plain((ROOT / "papers" / "provenance-pipelines.txt").read_bytes()).text
    write("evidence_extractor", sha256_hex(text.encode()), {
        "methods": "Instrumented twelve open-source pipelines and re-executed each in a fresh environment.",
        "population_or_dataset": "twelve open-source Python data science pipelines",
        "results": "8 of 12 pipelines changed outputs; recording versions restored 7 of those 8.",
        "limitations": "Python only; non-random selection.",
        "passages": [
            {"quote": "In this fixture, eight of the twelve pipelines produced different outputs when re-executed with updated library versions.",
             "role": "result", "section_hint": "Results", "summary": "Most pipelines changed outputs after updates."},
            {"quote": QUOTE, "role": "result", "section_hint": "Results", "summary": "Version records restored 7 of 8."},
            {"quote": "The study covered only Python pipelines, and the selection of pipelines was not random.",
             "role": "limitation", "section_hint": "Limitations", "summary": "Python only, non-random sample."},
            {"quote": "All pipelines became fully reproducible after applying our tool.",
             "role": "result", "section_hint": "Results", "summary": "Fabricated overstatement (must be dropped)."},
        ],
        "claims": [
            {"proposition": CLAIM, "category": "descriptive", "passage_indices": [1], "population_or_dataset":
             "twelve Python pipelines", "measure": "restored outputs", "comparison": None, "scope": "fixture study"},
            {"proposition": "All pipelines became fully reproducible.", "category": "causal", "passage_indices": [3],
             "population_or_dataset": None, "measure": None, "comparison": None, "scope": None},
        ],
    })
    write("support_assessor", sha256_hex((CLAIM + "||" + QUOTE).encode()), {
        "verdict": "supports", "scope_notes": "Limited to the twelve fixture pipelines.", "strength_mismatch": False,
        "uncertainty": "Single small non-random sample."})
    inputs = {"project": {"topic": "reproducibility of data pipelines"},
              "papers": [{"doi": "10.14778/3415478.3415556", "title": "x"}, {"doi": "10.1007/978-3-030-80960-7_17", "title": "x"},
                         {"doi": "10.18122/td.2050.boisestate", "title": "x"}, {"doi": "10.2139/ssrn.7323260", "title": "x"},
                         {"doi": "10.1088/2631-8695/ae9124/data1", "title": "x"}]}
    write("opportunity_generator", opportunity_fixture_key(inputs), {
        "proposals": [
            {"title": "Version drift across non-Python pipelines", "research_question":
             "Does recording library versions restore outputs for R and Julia data pipelines as it does for Python?",
             "cfp_alignment": "Reproducibility of data-intensive experiments (CFP topic).",
             "potential_contribution": "Evidence on whether version recording generalises beyond Python.",
             "closest_work_paper_ids": ["not-a-provided-id"], "how_it_differs": "Different language ecosystems.",
             "boundary_conditions": "Open-source pipelines with public inputs.", "data_availability": "Public repositories.",
             "time_estimate_weeks_low": 6, "time_estimate_weeks_high": 10, "compute_estimate": "a few CPU-days",
             "ethics_constraints": None, "threats_to_novelty": ["unpublished replications may exist"],
             "novelty_caveat": "Novelty is a hypothesis based on the documented search only.",
             "study_types": [{"study_type": "empirical_quantitative", "venue_category": "full_paper",
                              "fit_rationale": "Measured re-execution outcomes.", "required_inputs": ["pipeline corpus"],
                              "reporting_standard": None, "blockers": []},
                             {"study_type": "systematic_review", "venue_category": "full_paper",
                              "fit_rationale": "Could survey reproducibility studies.", "required_inputs": ["protocol"],
                              "reporting_standard": "PRISMA", "blockers": []}],
             "rationale": {"problem": "Pipelines change outputs when dependencies change.",
                           "gap": "Evidence is limited to Python pipelines.", "gap_evidence_passage_ids": ["fabricated-passage"],
                           "importance_to_venue": "Directly matches the reproducibility topic.",
                           "intended_contribution": "Cross-ecosystem measurement.",
                           "success_criterion": "Restoration rate measured for at least two ecosystems."}},
            {"title": "Provenance granularity trade-offs", "research_question":
             "Which provenance granularity is sufficient to restore pipeline outputs at acceptable capture cost?",
             "cfp_alignment": "Provenance capture and lineage systems (CFP topic).",
             "potential_contribution": "A cost/benefit characterisation of provenance granularity.",
             "closest_work_paper_ids": [], "how_it_differs": "Focus on granularity rather than presence.",
             "boundary_conditions": "Batch pipelines.", "data_availability": "Public pipelines.",
             "time_estimate_weeks_low": 8, "time_estimate_weeks_high": 14, "compute_estimate": "moderate",
             "ethics_constraints": None, "threats_to_novelty": ["workflow-system literature may cover this"],
             "novelty_caveat": "Requires a closer search of workflow-system venues.",
             "study_types": [{"study_type": "methodological", "venue_category": "full_paper",
                              "fit_rationale": "Proposes and evaluates capture strategies.", "required_inputs": ["benchmark"],
                              "reporting_standard": None, "blockers": []}],
             "rationale": {"problem": "Capturing all provenance is costly.", "gap": "Granularity needs are unknown.",
                           "gap_evidence_passage_ids": [], "importance_to_venue": "Lineage systems topic.",
                           "intended_contribution": "Guidance on granularity.", "success_criterion": "Measured trade-off curve."}},
        ],
        "negative_findings": ["Version recording for Python pipelines is already studied."]})
    print("fixtures written; text key", sha256_hex(text.encode())[:12])


if __name__ == "__main__":
    main()
