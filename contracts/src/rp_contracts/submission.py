"""Submission preparation contracts (PRODUCT_SPEC §2.14, §2.15).

* Author records: humans only, explicit order, contribution statements, competing interests, funding. Assent is
  recorded per author (in-product approval or a recorded offline attestation); it is never inferred.
* Deadline policy evaluator: evaluates the *intended next action* against only the deadlines/prerequisites that govern
  it. Unknown scope or timezone needs a human resolution; unrelated passed deadlines are context, not ineligibility.
* Readiness stages follow the exact sequence of §2.15; advancing a label requires its evidence.
* The platform does not submit externally.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EVALUATOR_VERSION = "rp-deadline-evaluator/1"
READINESS_VERSION = "rp-readiness/1"
STAGES = ["research_proposal", "research_in_progress", "manuscript_draft", "scientific_review_complete",
          "compliance_checked", "approved_for_export", "submission_ready_package"]
CREDIT_ROLES = {"conceptualization", "data_curation", "formal_analysis", "funding_acquisition", "investigation",
                "methodology", "project_administration", "resources", "software", "supervision", "validation",
                "visualization", "writing_original_draft", "writing_review_editing"}
NON_HUMAN = re.compile(r"\b(chat\s?gpt|gpt-?\d|claude|gemini|copilot|llama|bard|large language model|llm|ai assistant|"
                       r"artificial intelligence|language model|bot)\b", re.I)
UNAPPROVED_NOTICE = ("UNAPPROVED - for author review only. This package has not been signed off (H4) and is not a "
                     "submission-ready package. The platform does not submit to any venue.")
AUTHOR_APPROVAL_TEXT = ("I have read this exact manuscript version, agree to be listed as an author in the stated order "
                        "with the stated contribution, and approve its submission.")
OFFLINE_ATTESTATION_TEXT = ("I recorded this author's explicit approval of this exact manuscript version, given outside "
                            "the platform; the evidence is attached or described. Silence or an invitation is not assent.")


class AuthorIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    email: str | None = Field(default=None, max_length=320)
    affiliations: list[str] = Field(default_factory=list)
    orcid: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
    user_id: str | None = None
    corresponding: bool = False
    contribution_roles: list[str] = Field(default_factory=list)
    contribution_statement: str = Field(min_length=10, max_length=4000)
    competing_interests: str = Field(min_length=2, max_length=4000, description="'None declared' if none")
    funding: str = Field(min_length=2, max_length=4000, description="'No external funding' if none")
    human_confirmed: bool = Field(description="the entry describes a natural person (AI tools cannot be authors)")

    @field_validator("contribution_roles")
    @classmethod
    def _roles(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in CREDIT_ROLES]
        if bad:
            raise ValueError(f"unknown CRediT roles: {bad}")
        return v


def author_problems(authors: list[AuthorIn]) -> list[str]:
    out = []
    if not authors:
        out.append("list at least one author")
    if sum(1 for a in authors if a.corresponding) != 1:
        out.append("exactly one corresponding author is required")
    for i, a in enumerate(authors, start=1):
        if not a.human_confirmed or NON_HUMAN.search(a.name):
            out.append(f"author {i} ({a.name}): AI tools cannot be listed as authors; describe AI use in the disclosure")
        if not a.contribution_roles:
            out.append(f"author {i} ({a.name}): record at least one contribution role")
    emails = [a.email.lower() for a in authors if a.email]
    if len(emails) != len(set(emails)):
        out.append("duplicate author e-mail addresses")
    return out


class DisclosuresIn(BaseModel):
    competing_interests: str = Field(min_length=2, max_length=8000)
    funding: str = Field(min_length=2, max_length=8000)
    ethics_statement: str = Field(min_length=2, max_length=8000)
    ai_use: str = Field(min_length=10, max_length=8000, description="what AI tools were used for, in the authors' words")
    ai_policy_text: str = Field(min_length=10, max_length=20000, description="the venue/publisher policy text as published")
    ai_policy_source: str = Field(min_length=4, max_length=2000, description="URL or rule reference of that policy text")
    ai_policy_interpretation: str = Field(min_length=10, max_length=8000,
                                          description="the researcher's reading of what the policy permits and requires")
    data_availability: str | None = Field(default=None, max_length=8000)


# --------------------------------------------------------------------------- deadline policy evaluator
class DeadlineIn(BaseModel):
    id: str
    kind: str
    due_at: datetime | None
    timezone: str | None
    governs: list[str]
    mandatory: bool | None
    applicability: str | None = None
    status: str | None = None
    prerequisite_for: list[str] = Field(default_factory=list)


class EligibilityResult(BaseModel):
    action: str
    status: Literal["eligible", "ineligible", "needs_human_resolution"]
    evaluated_at: datetime
    governing: list[dict[str, Any]]
    context: list[dict[str, Any]]
    pending_prerequisites: list[dict[str, Any]]
    reasons: list[str]
    evaluator: str = EVALUATOR_VERSION


PRIMARY = {"new_submission": "full_paper", "abstract_registration": "abstract_registration", "rebuttal": "rebuttal",
           "camera_ready": "camera_ready", "artifact_submission": "artifact", "author_registration": "author_registration"}


def evaluate_deadlines(deadlines: list[DeadlineIn], action: str, now: datetime,
                       completed_prerequisites: set[str] | None = None) -> EligibilityResult:
    done = completed_prerequisites or set()
    governing, context, pending, reasons = [], [], [], []
    status = "eligible"
    for d in deadlines:
        if d.applicability == "not_applicable" or d.status in ("rejected",):
            continue
        row = {"id": d.id, "kind": d.kind, "due_at": d.due_at.isoformat() if d.due_at else None, "timezone": d.timezone,
               "mandatory": d.mandatory}
        governs = action in d.governs or action in d.prerequisite_for
        if not governs:
            if d.due_at and d.due_at < now:
                context.append({**row, "note": "passed, but it does not govern this action"})
            continue
        governing.append(row)
        if d.due_at is None or not d.timezone or d.status == "needs_human_resolution":
            status = "needs_human_resolution" if status != "ineligible" else status
            reasons.append(f"{d.kind}: the date, time zone or scope is unresolved; confirm it from the official source")
            continue
        primary = PRIMARY.get(action) == d.kind
        if primary:
            if d.due_at < now:
                status = "ineligible"
                reasons.append(f"the {d.kind} deadline passed at {d.due_at.isoformat()}; keep the research artifacts and "
                               "consider another venue (extensions count only from an official source)")
        else:  # a prerequisite of the intended action, e.g. mandatory abstract registration before a new submission
            if d.kind in done:
                continue
            if d.mandatory is False:
                continue
            if d.due_at < now:
                if d.mandatory:
                    status = "ineligible"
                    reasons.append(f"the mandatory {d.kind} closed at {d.due_at.isoformat()} and was not completed")
                else:
                    status = "needs_human_resolution" if status != "ineligible" else status
                    reasons.append(f"{d.kind} passed; the source does not say whether it is mandatory")
            else:
                pending.append({**row, "note": f"complete {d.kind} before {d.due_at.isoformat()}"})
    if not governing:
        status = "needs_human_resolution"
        reasons.append(f"no recorded deadline governs '{action}'; confirm the submission path from the official source")
    return EligibilityResult(action=action, status=status, evaluated_at=now, governing=governing, context=context,
                             pending_prerequisites=pending, reasons=reasons)


# --------------------------------------------------------------------------- readiness
def readiness_stage(state: str, gates: dict[str, bool], package_verified: bool, eligibility_ok: bool) -> str:
    """The highest label whose evidence is present, following the exact §2.15 sequence."""
    if state in ("CREATED", "TARGET_REVIEW", "DIRECTION_REVIEW", "PROTOCOL_REVIEW"):
        return "research_proposal"
    if state in ("RESEARCH_ACTIVE", "OUTCOME_REVIEW"):
        return "research_in_progress"
    stage = "manuscript_draft"
    if gates.get("manuscript.complete") and gates.get("review.passed"):
        stage = "scientific_review_complete"
        if gates.get("compliance.checked") and gates.get("integrity.checked"):
            stage = "compliance_checked"
            if gates.get("h4.approved") and state in ("APPROVED_FOR_EXPORT", "PACKAGE_READY"):
                stage = "approved_for_export"
                if state == "PACKAGE_READY" and package_verified and eligibility_ok:
                    stage = "submission_ready_package"
    return stage


EXPORT = [AuthorIn, DisclosuresIn, EligibilityResult]
