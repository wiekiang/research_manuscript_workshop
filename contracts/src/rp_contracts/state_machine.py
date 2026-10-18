"""Canonical project lifecycle (PRODUCT_SPEC §3).

This table is the single declarative source for allowed transitions and the gate IDs that the
FastAPI transition service must evaluate before committing a transition. Workers import it only to
*request* transitions; they never apply them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import ProjectState as S

MAIN_SEQUENCE: list[S] = [
    S.CREATED,
    S.TARGET_REVIEW,
    S.DIRECTION_REVIEW,
    S.PROTOCOL_REVIEW,
    S.RESEARCH_ACTIVE,
    S.OUTCOME_REVIEW,
    S.DRAFTING,
    S.SCIENTIFIC_REVIEW,
    S.COMPLIANCE_REVIEW,
    S.FINAL_APPROVAL,
    S.APPROVED_FOR_EXPORT,
    S.PACKAGE_READY,
]
OVERLAYS = {S.PAUSED, S.BLOCKED, S.CANCELLED}
STATE_INDEX = {s: i for i, s in enumerate(MAIN_SEQUENCE)}


@dataclass(frozen=True)
class TransitionRule:
    source: S
    target: S
    gates: tuple[str, ...]
    description: str
    # Which actors may request it: "user" (via a human action endpoint), "service" (Temporal), or both.
    actors: frozenset[str] = field(default_factory=lambda: frozenset({"user", "service"}))


FORWARD_RULES: list[TransitionRule] = [
    TransitionRule(S.CREATED, S.TARGET_REVIEW, ("target.selected",), "An official (or exploratory) target is selected"),
    TransitionRule(
        S.TARGET_REVIEW,
        S.DIRECTION_REVIEW,
        ("cfp.confirmed",),
        "Official CFP snapshot exists, track selected and every blocking rule confirmed by a human",
    ),
    TransitionRule(S.DIRECTION_REVIEW, S.PROTOCOL_REVIEW, ("h1.approved",), "H1 research direction approved"),
    TransitionRule(S.PROTOCOL_REVIEW, S.RESEARCH_ACTIVE, ("h2.approved",), "H2 frozen protocol approved"),
    TransitionRule(
        S.RESEARCH_ACTIVE,
        S.OUTCOME_REVIEW,
        ("method.required_stages_complete",),
        "All required method-workflow stages produced committed, validated outputs",
    ),
    TransitionRule(S.OUTCOME_REVIEW, S.DRAFTING, ("h3.approved",), "H3 outcomes and interpretation approved"),
    TransitionRule(
        S.DRAFTING, S.SCIENTIFIC_REVIEW, ("manuscript.complete",), "A committed manuscript version covers all sections"
    ),
    TransitionRule(
        S.SCIENTIFIC_REVIEW,
        S.COMPLIANCE_REVIEW,
        ("review.passed",),
        "Independent review functions frozen, meta-review complete, no open blocker/major findings",
    ),
    TransitionRule(
        S.COMPLIANCE_REVIEW,
        S.FINAL_APPROVAL,
        ("compliance.checked", "integrity.checked", "readiness.pre_approval"),
        "Compile, compliance and integrity checks done; pre-approval readiness assessment recorded",
    ),
    TransitionRule(
        S.FINAL_APPROVAL,
        S.APPROVED_FOR_EXPORT,
        (
            "h4.approved",
            "approvals.h1_to_h4_current",
            "method.enabled_for_submission",
            "contribution.recorded",
            "blockers.none",
        ),
        "Corresponding author signed the frozen content manifest; all gates current",
    ),
    TransitionRule(
        S.APPROVED_FOR_EXPORT,
        S.PACKAGE_READY,
        ("package.verified", "eligibility.current", "approvals.h1_to_h4_current"),
        "Package content hashes match the H4 manifest and submission eligibility is current",
    ),
]

_FORWARD = {(r.source, r.target): r for r in FORWARD_RULES}


@dataclass(frozen=True)
class TransitionCheck:
    allowed: bool
    kind: str  # forward | reopen | overlay | resume | none
    gates: tuple[str, ...] = ()
    reason: str = ""


def check_transition(current: S, requested: S, resume_state: S | None = None) -> TransitionCheck:
    """Structural check only. Gate evaluation happens in the API transition service."""
    if current == S.CANCELLED:
        return TransitionCheck(False, "none", reason="project is cancelled")
    if requested == current:
        return TransitionCheck(False, "none", reason="project is already in the requested state")
    if requested in OVERLAYS:
        if current in OVERLAYS and requested != S.CANCELLED:
            return TransitionCheck(False, "none", reason=f"cannot apply {requested} while {current}")
        return TransitionCheck(True, "overlay")
    if current in OVERLAYS:
        if resume_state is None or requested != resume_state:
            return TransitionCheck(False, "none", reason=f"resume must target the saved state {resume_state}")
        return TransitionCheck(True, "resume")
    rule = _FORWARD.get((current, requested))
    if rule:
        return TransitionCheck(True, "forward", gates=rule.gates)
    if STATE_INDEX[requested] < STATE_INDEX[current]:
        # Reopening an earlier gate is only legal through dependency invalidation or an explicit
        # researcher rerun; the transition service records the cause.
        return TransitionCheck(True, "reopen")
    return TransitionCheck(False, "none", reason=f"{current} -> {requested} is not a permitted transition")


def gate_state_for(gate_id: str) -> S:
    """The state a project returns to when a gate it already passed is invalidated."""
    for rule in FORWARD_RULES:
        if gate_id in rule.gates:
            return rule.source
    raise KeyError(gate_id)


def transition_table() -> list[dict[str, object]]:
    return [
        {"from": r.source.value, "to": r.target.value, "gates": list(r.gates), "description": r.description}
        for r in FORWARD_RULES
    ]
