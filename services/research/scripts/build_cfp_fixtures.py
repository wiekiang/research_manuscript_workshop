"""Regenerate recorded fixture-model responses for the fixture CFPs (tests/demos only).

The recordings are written by hand to resemble a model's output for the fictional ICRDS 2027 CFP, and they
contain two deliberate defects so tests can prove the pipeline catches them:
  * a fabricated `fees.statement` rule whose quote does not occur in the source;
  * a full-paper deadline of 2027-01-22 although the source says January 21.
"""

from __future__ import annotations

import json
from pathlib import Path

from rp_contracts.hashing import sha256_hex
from rp_research.fetch.text import extract_html

ROOT = Path(__file__).resolve().parents[1] / "src" / "rp_research" / "fixtures"


def rule(key, cat, track, text, value, quote, blocking=True, unit=None, unc=None):
    return {"rule_key": key, "category": cat, "track": track, "value_text": text, "value": value, "unit": unit,
            "blocking": blocking, "quote": quote, "uncertainty": unc}


def dl(kind, date, time, tz, quote, mandatory=None, unc=None):
    return {"deadline_kind": kind, "track": None, "date": date, "time": time, "timezone": tz, "mandatory": mandatory,
            "quote": quote, "uncertainty": unc}


def main() -> None:
    lt = extract_html((ROOT / "cfp" / "icrds2027.html").read_bytes())
    key = sha256_hex(lt.text.encode())
    rules = [
        rule("length.page_limit", "length", "Research Papers Track", "At most 10 pages excluding references and appendices",
             "10", "Research papers must not exceed 10 pages, excluding references and appendices.", unit="pages"),
        rule("template.family", "template", "Research Papers Track", "ACM primary article template, sigconf option",
             "acm_acmart", "Submissions must use the ACM primary article template (acmart, sigconf option)."),
        rule("anonymization.mode", "anonymization", "Research Papers Track", "Double-blind review; anonymized submissions",
             "double_blind", "The review process is double-blind."),
        rule("abstract.word_limit", "abstract", "Research Papers Track", "Abstract at most 250 words", "250",
             "The abstract must not exceed 250 words.", unit="words"),
        rule("supplementary.policy", "supplementary", "Research Papers Track",
             "Supplementary material up to 50 MB may accompany the paper; reviewers need not consult it", "50MB",
             "Supplementary material up to 50 MB may be uploaded together with the paper"),
        rule("length.page_limit", "length", "Short Papers Track", "At most 4 pages excluding references", "4",
             "Short papers are limited to 4 pages, excluding references.", unit="pages"),
        rule("anonymization.mode", "anonymization", "Short Papers Track", "Same anonymization rules as research papers",
             "double_blind", "Short papers follow the same anonymization rules as research papers."),
        rule("dual_submission.policy", "dual_submission", None, "Must not be under review elsewhere", None,
             "Papers submitted to ICRDS 2027 must not be under review elsewhere"),
        rule("prior_publication.policy", "prior_publication", None, "Must not have been previously published in a peer-reviewed venue",
             None, "must not have been previously published in a peer-reviewed venue"),
        rule("preprint.policy", "preprint", None, "arXiv preprints permitted if the title differs", "permitted_with_different_title",
             "Posting a preprint on arXiv is permitted, provided the title differs from the submitted version."),
        rule("ai_policy.statement", "ai_policy", None,
             "Generative AI may be used for language editing; other uses must be disclosed", None,
             "Authors may use generative AI tools for language editing; any other use must be disclosed in the acknowledgments or as otherwise specified by the publisher.",
             unc="Disclosure location depends on unspecified publisher policy"),
        rule("ethics.requirement", "ethics", None, "Human-subjects studies must state whether IRB approval was obtained",
             None, "Studies involving human subjects must state whether ethics approval was obtained from an institutional review board."),
        rule("submission_system.name", "submission_system", None, "HotCRP", "hotcrp",
             "Papers are submitted through HotCRP", blocking=False),
        rule("fees.statement", "fees", None, "Registration fee of 500 EUR", "500 EUR",
             "The registration fee is 500 EUR per paper.", blocking=False),  # fabricated: not in the source
    ]
    deadlines = [
        dl("abstract_registration", "2027-01-14", None, "AoE", "Abstract registration (mandatory): Thursday, January 14, 2027 (AoE)", True),
        dl("full_paper", "2027-01-22", None, "AoE", "Full paper submission: January 21, 2027 (AoE)"),  # wrong date on purpose
        dl("rebuttal", "2027-03-03", None, None, "Author response (rebuttal) period: March 3-5, 2027", unc="range"),
        dl("notification", "2027-03-20", None, None, "Notification of acceptance: March 20, 2027"),
        dl("camera_ready", "2027-04-15", "23:59", "PDT", "Camera-ready deadline: April 15, 2027 at 23:59 PDT"),
        dl("author_registration", "2027-05-01", None, None, "Author registration deadline: May 1, 2027"),
    ]
    extraction = {
        "edition": {"conference_name": "ICRDS 2027: International Conference on Reproducible Data Systems",
                    "acronym": "ICRDS", "year": 2027, "location": "Lisbon, Portugal", "submission_url": "https://icrds27.hotcrp.example/",
                    "publication_outlet": "Conference proceedings", "publisher": "ACM", "official_site_url": None},
        "tracks": [
            {"name": "Research Papers Track", "description": "Full research papers", "paper_types": ["research paper"],
             "submission_categories": ["full paper"], "quote": "Research Papers Track"},
            {"name": "Short Papers Track", "description": "Short papers", "paper_types": ["short paper"],
             "submission_categories": ["short paper"], "quote": "Short Papers Track"},
        ],
        "rules": rules, "deadlines": deadlines,
        "uncertainties": ["Rebuttal is a period; the start date is recorded", "No timezone stated for several dates"],
    }
    checks = []
    for i, r in enumerate(rules):
        verdict, issue = "supported", None
        if r["rule_key"] == "fees.statement":
            verdict, issue = "unsupported", "The source does not mention a registration fee."
        if r["rule_key"] == "ai_policy.statement":
            verdict, issue = "unclear", "Where to disclose depends on a publisher policy that the CFP does not quote."
        checks.append({"kind": "rule", "index": i, "verdict": verdict, "issue": issue})
    for i, d in enumerate(deadlines):
        verdict, issue = "supported", None
        if d["deadline_kind"] == "full_paper":
            verdict, issue = "unsupported", "The source states January 21, 2027, not January 22."
        if d["timezone"] is None:
            verdict, issue = "unclear", "No timezone is stated for this date."
        checks.append({"kind": "deadline", "index": i, "verdict": verdict, "issue": issue})
    validation = {"checks": checks, "missed_items": []}
    for agent, out in (("cfp_extractor", extraction), ("cfp_validator", validation)):
        d = ROOT / "model" / agent
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(json.dumps({"fixture_for": "icrds2027.html", "output": out}, indent=2) + "\n")
    print("fixture key", key)


if __name__ == "__main__":
    main()
