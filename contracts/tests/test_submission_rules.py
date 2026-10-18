"""Deadline policy evaluator, readiness labels and author rules (PRODUCT_SPEC §2.14-2.15)."""

from __future__ import annotations

from datetime import UTC, datetime

from rp_contracts.submission import AuthorIn, DeadlineIn, author_problems, evaluate_deadlines, readiness_stage


def dl(kind, due, governs, mandatory=True, tz="AoE", **kw):
    return DeadlineIn(id=kind, kind=kind, due_at=datetime.fromisoformat(due) if due else None, timezone=tz,
                      governs=governs, mandatory=mandatory, **kw)


SCHEDULE = [dl("abstract_registration", "2027-01-15T11:59:00+00:00", ["abstract_registration", "new_submission"]),
            dl("full_paper", "2027-01-22T11:59:00+00:00", ["new_submission"]),
            dl("camera_ready", "2027-04-16T06:59:00+00:00", ["camera_ready"]),
            dl("author_registration", "2027-05-01T23:59:00+00:00", ["author_registration"])]


def at(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_eligible_before_deadlines_with_pending_registration():
    r = evaluate_deadlines(SCHEDULE, "new_submission", at("2026-10-18T00:00:00"))
    assert r.status == "eligible" and [p["kind"] for p in r.pending_prerequisites] == ["abstract_registration"]
    assert {g["kind"] for g in r.governing} == {"abstract_registration", "full_paper"}


def test_passed_mandatory_registration_blocks_unregistered_new_submission():
    r = evaluate_deadlines(SCHEDULE, "new_submission", at("2027-01-18T00:00:00"))
    assert r.status == "ineligible" and "abstract_registration" in r.reasons[0]
    ok = evaluate_deadlines(SCHEDULE, "new_submission", at("2027-01-18T00:00:00"), {"abstract_registration"})
    assert ok.status == "eligible"


def test_passed_submission_deadline_blocks_but_unrelated_deadline_is_context():
    r = evaluate_deadlines(SCHEDULE, "new_submission", at("2027-01-23T00:00:00"), {"abstract_registration"})
    assert r.status == "ineligible" and "another venue" in r.reasons[0]
    cr = evaluate_deadlines(SCHEDULE, "camera_ready", at("2027-02-01T00:00:00"))
    assert cr.status == "eligible" and {c["kind"] for c in cr.context} == {"abstract_registration", "full_paper"}
    late = evaluate_deadlines(SCHEDULE, "new_submission", at("2027-01-20T00:00:00"), {"abstract_registration"})
    assert late.status == "eligible", "a later camera-ready/author-registration deadline never blocks a new manuscript"


def test_unknown_timezone_or_scope_needs_human_resolution():
    s = [dl("full_paper", "2027-01-22T11:59:00+00:00", ["new_submission"], tz=None)]
    assert evaluate_deadlines(s, "new_submission", at("2026-10-18T00:00:00")).status == "needs_human_resolution"
    assert evaluate_deadlines([], "new_submission", at("2026-10-18T00:00:00")).status == "needs_human_resolution"


def test_readiness_labels_follow_the_exact_sequence():
    g = {"manuscript.complete": True, "review.passed": True, "compliance.checked": True, "integrity.checked": True,
         "h4.approved": True}
    assert readiness_stage("PROTOCOL_REVIEW", g, True, True) == "research_proposal"
    assert readiness_stage("COMPLIANCE_REVIEW", {**g, "integrity.checked": False}, False, False) == "scientific_review_complete"
    assert readiness_stage("FINAL_APPROVAL", g, False, False) == "compliance_checked"
    assert readiness_stage("PACKAGE_READY", g, True, False) == "approved_for_export", "eligibility failing removes the label"
    assert readiness_stage("PACKAGE_READY", g, True, True) == "submission_ready_package"


def author(name, corresponding=False, human=True):
    return AuthorIn(name=name, corresponding=corresponding, contribution_roles=["investigation"],
                    contribution_statement="Ran the analysis.", competing_interests="None declared",
                    funding="No external funding", human_confirmed=human)


def test_ai_cannot_be_an_author_and_one_corresponding_author():
    assert author_problems([author("Ada Lovelace", True)]) == []
    assert any("AI tools" in p for p in author_problems([author("Ada Lovelace", True), author("Claude")]))
    assert any("AI tools" in p for p in author_problems([author("Ada Lovelace", True), author("Bob", human=False)]))
    assert any("corresponding" in p for p in author_problems([author("Ada Lovelace"), author("Bob")]))
