"""Recorded reviewer responses for the M7 fixture manuscript (the M6 path after its two defective spans were fixed).

Keys are the fixture keys of the frozen review inputs (scientific: manuscript content digest + protocol hash;
meaning checker: claim, opened evidence and linked spans). They were captured with RP_FIXTURE_MISSING_DIR from the
deterministic M7 test scenario. Round 1 contains one scope-drift span (plural "Studies" for a single eight-pipeline
study) and one scientific major finding (generalisation in the conclusion); round 2 is the re-review after the author
applied the suggested wording.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "rp_research" / "fixtures" / "model"

SCI_FINDING = {
    "severity": "major", "category": "conclusions",
    "issue": "The conclusion generalises from eight R pipelines",
    "rationale": "The conclusion states that version records help restore R pipeline outputs in general, while the "
                 "evidence is an exploratory sample of eight public pipelines.",
    "check": "Compare the conclusion sentence with the sample size in the Method and the H3 limitations.",
    "proposed_fix": "Qualify the sentence: 'In this exploratory sample of eight R pipelines, ...'.",
    "span_ids": ["S-559ceb2c4a"], "claim_ids": [],
}
SCI = {
    "question": "The research question is specific and scoped to R pipelines after H1.",
    "protocol": "The frozen protocol was followed; the exploratory framing matches the methodology review.",
    "evidence": "One literature claim and one independently checked result support the factual sentences.",
    "contribution": "The contribution is reported as partial, consistent with the gap assessment.",
    "conclusions": "Mostly within the evidence; one conclusion sentence generalises beyond the sample.",
    "findings": [SCI_FINDING],
}
SUGGESTED = "One study of eight Python pipelines found that recording library versions restored seven of them."

RECORDINGS = {
    # round 1 and round 2: scientific review (content digests differ; the same finding recurs on the unchanged span)
    ("scientific_reviewer", "46528880f95e5c43e0d4ce2de6f65a3c65101df86f45a21ef3df81af8f0ef122"): SCI,
    # round 1: result claim CLM-0002 (reused unchanged in round 2)
    ("meaning_checker", "05d483fc9d586b747b4ae17847ac36f3aa08eff2eb5b1f7b4a38a9e9b28c155d"): {"spans": [
        {"span_id": "S-41c3141e8e", "verdict": "faithful", "rationale": "Matches RES-001 (6/8, 0.75).", "suggested_wording": None},
        {"span_id": "S-47b6b7ef05", "verdict": "faithful", "rationale": "Restates the claim exactly.", "suggested_wording": None}]},
    # round 1: literature claim CLM-0001
    ("meaning_checker", "292a62780747dcfe12cc7607c358707135f34fe0809025ab2aa0387987d7863b"): {"spans": [
        {"span_id": "S-3e3df22b74", "verdict": "faithful", "rationale": "Same scope and strength as the passage.",
         "suggested_wording": None},
        {"span_id": "S-6f8b6dcd3d", "verdict": "faithful", "rationale": "Attributes the finding to prior work.",
         "suggested_wording": None},
        {"span_id": "S-b3b22ce54a", "verdict": "scope_drift",
         "rationale": "The passage reports one study of eight pipelines; 'Studies ... found' implies several studies.",
         "suggested_wording": SUGGESTED}]},
}


def main() -> None:
    extra = json.loads((Path(__file__).with_name("m7_round2_keys.json")).read_text()) \
        if Path(__file__).with_name("m7_round2_keys.json").exists() else {}
    recs = dict(RECORDINGS)
    if extra.get("scientific"):
        recs[("scientific_reviewer", extra["scientific"])] = SCI
    if extra.get("meaning_lit"):
        recs[("meaning_checker", extra["meaning_lit"]["key"])] = {"spans": [
            {"span_id": s, "verdict": "faithful", "rationale": "Within the scope and strength of the passage.",
             "suggested_wording": None} for s in extra["meaning_lit"]["span_ids"]]}
    for (agent, key), out in recs.items():
        (ROOT / agent).mkdir(parents=True, exist_ok=True)
        (ROOT / agent / f"{key}.json").write_text(json.dumps({"fixture_for": "M7 tests", "output": out}, indent=2) + "\n")
        print(agent, key[:12])


if __name__ == "__main__":
    main()
