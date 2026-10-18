"""Recorded section-writer responses for the M6 fixture project (the M5 empirical path plus one verified paper).

Recordings are keyed by the writer signature of the frozen brief (section, mode, research question, claim keys and
propositions, result keys, gap status, instructions). Two spans are deliberately defective so tests exercise the
deterministic checks: an uncited factual sentence in Related Work (unresolved-claim queue) and a sentence in the
Discussion claiming the gap was filled although the researcher assessed it as partially addressed.
"""

from __future__ import annotations

import json
from pathlib import Path

from rp_research.agents.writer import writer_fixture_key

ROOT = Path(__file__).resolve().parents[1] / "src" / "rp_research" / "fixtures" / "model" / "section_writer"

BRIEF = {
    "mode": "paper",
    "research_question": "Does recording library versions restore outputs for R and Julia data pipelines as it does for "
                         "Python? (scoped to R pipelines)",
    "claims": [{"key": "CLM-0001", "proposition": "Recording library versions restored most pipelines whose outputs "
                                                  "changed after re-execution."},
               {"key": "CLM-0002", "proposition": "The restoration classifier reached 0.75 accuracy (6/8) on the eight "
                                                  "pipelines."}],
    "results": [{"key": "RES-001"}],
    "matrix": {"gap_resolution": {"status": "partially_addressed"}},
}


def s(text, kind, claims=(), results=()):
    return {"text": text, "kind": kind, "claim_ids": list(claims), "result_keys": list(results)}


SECTIONS = {
    "abstract": [[
        s("Data pipelines often stop reproducing their outputs when the libraries they depend on change.", "framing"),
        s("For Python pipelines, recording library versions restored most pipelines whose outputs changed after "
          "re-execution.", "prior_work", ["CLM-0001"]),
        s("We test whether the same holds for pipelines written in R.", "framing"),
        s("On eight public R pipelines, a restoration classifier reached 0.75 accuracy (6/8).", "observed_result",
          ["CLM-0002"], ["RES-001"]),
        s("The sample is small and exploratory, so the result partly addresses the gap for R only.", "limitation"),
    ]],
    "introduction": [[
        s("Re-executing a data pipeline months later frequently yields different outputs.", "framing"),
        s("Prior work on Python pipelines reports that recording library versions restored most pipelines whose "
          "outputs changed after re-execution.", "prior_work", ["CLM-0001"]),
    ], [
        s("Whether this transfers to R, where package management differs, has not been measured.", "framing"),
        s("We ask whether recording library versions restores outputs for R pipelines as it does for Python.", "framing"),
        s("We hypothesise that version records help, but less reliably than for Python.", "hypothesis"),
    ]],
    "related_work": [[
        s("Studies of Python pipelines found that recording library versions restored most pipelines whose outputs "
          "changed after re-execution.", "prior_work", ["CLM-0001"]),
        s("Pip is the most widely used package manager for data science.", "prior_work"),
        s("These findings motivate testing the approach in another ecosystem.", "interpretation"),
    ]],
    "method": [[
        s("We selected eight public R pipelines with public inputs and no credentials.", "method"),
        s("Each pipeline was re-executed with and without its recorded library versions, and its outputs were labelled "
          "as restored or not.", "method"),
        s("A restoration classifier was evaluated against these labels following the frozen protocol.", "method"),
    ]],
    "results": [[
        s("The restoration classifier reached 0.75 accuracy (6/8) on the eight pipelines.", "observed_result",
          ["CLM-0002"], ["RES-001"]),
        s("The accuracy was recomputed from the supplied raw outputs.", "method"),
    ]],
    "discussion": [[
        s("Recorded versions restored most affected R pipelines in this sample.", "interpretation"),
        s("Our study fills the gap for R pipelines.", "contribution_statement"),
        s("The pipelines that were not restored may depend on system libraries that version records do not capture.",
          "hypothesis"),
    ]],
    "limitations": [[
        s("Eight pipelines is a small, non-random sample, so the study is exploratory.", "limitation"),
        s("The experiment itself was not re-run by an independent party.", "limitation"),
    ]],
    "conclusion": [[
        s("Recording library versions appears to help restore R pipeline outputs, as reported for Python.", "interpretation"),
        s("Larger samples and other ecosystems are needed before generalising.", "limitation"),
    ]],
}
HEADINGS = {"abstract": "Abstract", "introduction": "Introduction", "related_work": "Related Work", "method": "Method",
            "results": "Results", "discussion": "Discussion", "limitations": "Limitations", "conclusion": "Conclusion"}
TABLES = {"results": [{"caption": "Restoration classifier accuracy on eight R pipelines", "result_keys": ["RES-001"]}]}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for key, paras in SECTIONS.items():
        fk = writer_fixture_key({"brief": BRIEF, "section": {"key": key}, "instructions": None})
        out = {"key": key, "heading": HEADINGS[key], "paragraphs": [{"spans": p} for p in paras],
               "tables": TABLES.get(key, []), "rationale": f"Fixture draft of the {HEADINGS[key]} section from the brief.",
               "open_questions": []}
        (ROOT / f"{fk}.json").write_text(json.dumps({"fixture_for": "M6 tests", "output": out}, indent=2) + "\n")
        print(key, fk[:12])


if __name__ == "__main__":
    main()
