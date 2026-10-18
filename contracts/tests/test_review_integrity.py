"""Deterministic M7 review and integrity rules."""

from __future__ import annotations

from rp_contracts.integrity import run_integrity, summarize
from rp_contracts.review import (
    check_key,
    check_literature_source,
    check_result_source,
    compliance_findings,
    evaluate_compliance,
    meta_review,
    sample_noncritical,
)

ETHICS = {"involves_human_participants": False, "personal_data": False, "sensitive_data": False,
          "restricted_datasets": False, "institutional_approval": {"required": False, "status": "not_required"},
          "declaration_text_accepted": True}


def test_sampling_is_documented_and_deterministic():
    keys = [f"CLM-{i:04d}" for i in range(1, 31)]
    a, rest = sample_noncritical(keys, "seed")
    assert len(a) == 6 and len(rest) == 24 and set(a) | set(rest) == set(keys)
    assert sample_noncritical(keys, "seed") == (a, rest)
    assert sample_noncritical(keys[:4], "seed") == (keys[:4], [])


def test_missing_source_is_not_performed_never_passed():
    assert check_literature_source("q", None)["status"] == "not_performed"
    assert check_literature_source("restored seven pipelines", "We restored seven pipelines.")["status"] == "passed"
    assert check_literature_source("restored all pipelines", "We restored seven pipelines.")["status"] == "failed"
    assert check_result_source("accuracy 0.75 (6/8)", None)["status"] == "not_performed"
    m = [{"name": "accuracy", "value": 0.75, "n": 8, "numerator": 6, "denominator": 8}]
    assert check_result_source("accuracy 0.75 (6/8)", m)["status"] == "passed"
    assert check_result_source("accuracy 0.80", m)["status"] == "failed"


def test_check_reuse_key_changes_with_span_text_or_source():
    k = check_key("P", "h1", ["a", "b"])
    assert k == check_key("P", "h1", ["b", "a"])
    assert k != check_key("P", "h2", ["a", "b"]) and k != check_key("P", "h1", ["a", "c"])


def test_compliance_reads_rules_and_fails_closed():
    rules = [{"id": "r1", "rule_key": "length.page_limit", "value": "8", "quote": "8 pages", "quote_in_snapshot": True, "blocking": True},
             {"id": "r2", "rule_key": "anonymization.mode", "value": "double_blind", "quote": "double-blind", "quote_in_snapshot": True,
              "blocking": True},
             {"id": "r3", "rule_key": "abstract.word_limit", "value": "150", "quote": "150 words", "quote_in_snapshot": False,
              "blocking": True}]
    run = {"status": "compiled", "pages": 9, "options": {"anonymous": False}, "checks": {"citations.resolved": "passed"}}
    checks = {c.id: c for c in evaluate_compliance(rules=rules, compile_run=run, manuscript={"abstract_words": 100},
                                                    template={"family": "acmart", "archive_hash": "x"}, cfp_available=True)}
    assert checks["rule:length.page_limit"].status == "failed"
    assert checks["rule:anonymization.mode"].status == "failed", "non-anonymous compile for a double-blind venue"
    assert checks["rule:abstract.word_limit"].status == "not_performed", "quote absent from the official snapshot"
    assert checks["anonymization.visual_inspection"].status == "manual_check"
    assert {f.severity for f in compliance_findings(list(checks.values()))} == {"blocker"}
    none = {c.id: c for c in evaluate_compliance(rules=[], compile_run=None, manuscript={}, template=None, cfp_available=False)}
    assert none["cfp.official_rules"].status == "not_performed" and none["compile.current_version"].status == "not_performed"


def test_meta_review_highlights_disagreements():
    meta = meta_review({
        "scientific": {"status": "performed", "findings": [{"severity": "major", "span_ids": ["S-1"], "claim_ids": []}]},
        "citation_evidence": {"status": "performed", "findings": [], "assessed_ok": {"span_ids": ["S-1"], "claim_ids": []}},
        "technical": {"status": "not_performed", "findings": [], "not_performed_detail": "no raw outputs"}})
    assert meta["disagreements"] == [{"span_id": "S-1", "flagged_by": ["scientific"], "judged_ok_by": "citation_evidence"}]
    assert meta["not_performed"][0]["function"] == "technical" and meta["counts"]["scientific"]["major"] == 1


def bundle(**over):
    b = {"spans": [{"span_id": "S-1", "kind": "observed_result", "text": "Accuracy was 0.75.", "origin": "ai",
                    "claim_ids": [], "result_keys": ["RES-001"], "issues": []}],
         "bibliography": [{"cite_key": "a2020x", "identity_status": "verified", "retracted": False}],
         "results": {"RES-001": {"assurance": "independently_checked", "protocol_hash": "h", "data_origin": "o",
                                 "data_rights": "r", "assessment_blockers": [], "failed_checks": []}},
         "frozen_protocol_hash": "h", "protocol": {"ethics_rights": ETHICS, "after_data_inspection_amendments": []},
         "contributions": [{"title": "c", "pii_classification": "none", "rights_statement": "mine"}], "figures": [],
         "sources": [], "template": {"license_note": "LPPL"}, "authors_emails": [],
         "declarations": {"competing_interests": "none", "funding": "none", "ai_use": "drafting assistance"}}
    b.update(over)
    return b


def statuses(b):
    return {c.id: c.status for c in run_integrity(b)}


def test_integrity_clean_bundle_passes_and_never_certifies():
    checks = run_integrity(bundle())
    s = summarize(checks)
    assert s["passed"] and "does not certify" in s["disclaimer"]


def test_integrity_fails_closed_on_fabricated_reference_and_declared_overstatement():
    st = statuses(bundle(bibliography=[{"cite_key": "fake", "identity_status": "not_found", "retracted": False}]))
    assert st["references.identity"] == "failed"
    declared = bundle(spans=[{"span_id": "S-1", "kind": "observed_result", "text": "The verified accuracy was 0.75.",
                              "origin": "ai", "claim_ids": [], "result_keys": ["RES-001"], "issues": []}],
                      results={"RES-001": {"assurance": "declared", "protocol_hash": "h", "data_origin": "o",
                                           "data_rights": "r", "assessment_blockers": [], "failed_checks": []}})
    assert statuses(declared)["results.wording_vs_assurance"] == "failed"
    assert statuses(bundle(declarations=None))["declarations"] == "not_performed"
    assert statuses(bundle(declarations={"competing_interests": "none", "funding": "none"}))["declarations"] == "failed"
    eth = {**ETHICS, "involves_human_participants": True, "institutional_approval": {"required": False, "status": "not_required"}}
    assert statuses(bundle(protocol={"ethics_rights": eth}))["ethics.rights"] == "failed"


def test_integrity_uncertainty_needs_decision():
    src = [{"id": "p1", "text": "Recording library versions allowed seven of those eight pipelines to be restored to "
                                "their original outputs after re-execution in the study."}]
    spans = [{"span_id": "S-2", "kind": "prior_work", "origin": "ai", "claim_ids": ["CLM-1"], "result_keys": [], "issues": [],
              "text": "Recording library versions allowed seven of those eight pipelines to be restored to their original outputs."}]
    checks = run_integrity(bundle(spans=spans, sources=src))
    ov = next(c for c in checks if c.id == "text.overlap")
    assert ov.status == "warning" and ov.requires_decision and "not comprehensive" in ov.limitations
    s = summarize(checks)
    assert not s["passed"] and s["awaiting_decision"] == ["text.overlap"]
    assert summarize(checks, {"text.overlap": {}})["passed"]
