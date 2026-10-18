"""Claim verification policy (PRODUCT_SPEC §2.6): versioned, immutable minimum-for-use rules and a pure evaluator.

`verified` means the current evidence relationship meets the active policy's minimum for the claim's category;
it is never a certification of truth. The API alone sets claim status by running this evaluator. Model-assisted
checks can never satisfy a rule that requires a human, and novelty/causal/comparative/ethics claims always
require human judgment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

REQUIREMENTS = {
    "identity_deterministic": "every cited source's identity verified deterministically against an authoritative record",
    "passage_inspectable": "an inspectable passage verified verbatim in the source text",
    "passage_fulltext": "the passage comes from full text (not only an abstract)",
    "support_assessed": "a model-assisted or human assessment that the passage supports the claim's scope",
    "support_human": "a human confirmed that the evidence supports the claim",
    "no_contradiction": "no unresolved contradicting evidence",
    "no_strength_mismatch": "the claim does not overstate the evidence (causality, generality, numbers)",
    "result_or_table": "a committed result artifact or a verified source table/numerical passage",
    "units_recorded": "units/denominator recorded for the numerical claim",
    "closest_work_assessed": "closest prior work or alternative explanations assessed",
    "human_judgment": "researcher scientific judgment recorded (cannot be satisfied by a model)",
    "authoritative_source": "an applicable authoritative source (official policy, rule or approval)",
}

HUMAN_ONLY = {"support_human", "human_judgment"}


class PolicyRule(BaseModel):
    id: str
    category: str
    requires: list[str]
    any_of: list[list[str]] = Field(default_factory=list, description="each inner list: at least one must hold")


class VerificationPolicy(BaseModel):
    version: str
    rules: list[PolicyRule]
    study_type_overrides: dict[str, list[PolicyRule]] = Field(default_factory=dict)

    def rule_for(self, category: str, study_type: str | None = None) -> PolicyRule:
        if study_type and study_type in self.study_type_overrides:
            for r in self.study_type_overrides[study_type]:
                if r.category == category:
                    return r
        for r in self.rules:
            if r.category == category:
                return r
        return next(r for r in self.rules if r.category == "descriptive")


POLICY_V1 = VerificationPolicy(version="claim-policy-1", rules=[
    PolicyRule(id="P1-identity", category="identity", requires=["identity_deterministic"]),
    PolicyRule(id="P1-descriptive", category="descriptive",
               requires=["identity_deterministic", "passage_inspectable", "support_assessed", "no_contradiction",
                         "no_strength_mismatch"]),
    PolicyRule(id="P1-numerical", category="numerical",
               requires=["result_or_table", "units_recorded", "support_assessed", "no_contradiction",
                         "no_strength_mismatch"],
               any_of=[["identity_deterministic", "result_or_table"]]),
    PolicyRule(id="P1-comparative", category="comparative",
               requires=["passage_inspectable", "closest_work_assessed", "human_judgment", "no_contradiction"]),
    PolicyRule(id="P1-causal", category="causal",
               requires=["passage_inspectable", "closest_work_assessed", "human_judgment", "no_contradiction",
                         "no_strength_mismatch"]),
    PolicyRule(id="P1-novelty", category="novelty", requires=["closest_work_assessed", "human_judgment"]),
    PolicyRule(id="P1-ethics", category="ethics_policy", requires=["authoritative_source", "human_judgment"]),
    PolicyRule(id="P1-conclusion", category="central_conclusion",
               requires=["support_assessed", "human_judgment", "no_contradiction"]),
])


@dataclass
class Evidence:
    """Facts the API gathered for one claim (from claim_support and verification records)."""

    identity_all_verified: bool = False
    has_verified_passage: bool = False
    passage_from_fulltext: bool = False
    model_support: bool = False
    human_support: bool = False
    contradiction_unresolved: bool = False
    strength_mismatch: bool = False
    has_result_or_table: bool = False
    units_recorded: bool = False
    closest_work_assessed: bool = False
    human_judgment: bool = False
    authoritative_source: bool = False

    def holds(self, req: str) -> bool:
        return {
            "identity_deterministic": self.identity_all_verified,
            "passage_inspectable": self.has_verified_passage,
            "passage_fulltext": self.passage_from_fulltext,
            "support_assessed": self.model_support or self.human_support,
            "support_human": self.human_support,
            "no_contradiction": not self.contradiction_unresolved,
            "no_strength_mismatch": not self.strength_mismatch,
            "result_or_table": self.has_result_or_table,
            "units_recorded": self.units_recorded,
            "closest_work_assessed": self.closest_work_assessed,
            "human_judgment": self.human_judgment,
            "authoritative_source": self.authoritative_source,
        }[req]


@dataclass
class Decision:
    status: str  # verified | unverified
    policy_version: str
    rule_id: str
    satisfied: list[str] = field(default_factory=list)
    outstanding: list[str] = field(default_factory=list)
    human_required: bool = False

    def as_dict(self) -> dict:
        return {"status": self.status, "policy_version": self.policy_version, "rule_id": self.rule_id,
                "satisfied": self.satisfied, "outstanding": self.outstanding, "human_required": self.human_required,
                "outstanding_descriptions": [REQUIREMENTS.get(o, o) for o in self.outstanding]}


def evaluate(policy: VerificationPolicy, category: str, ev: Evidence, study_type: str | None = None) -> Decision:
    rule = policy.rule_for(category, study_type)
    satisfied, outstanding = [], []
    for req in rule.requires:
        (satisfied if ev.holds(req) else outstanding).append(req)
    for group in rule.any_of:
        if any(ev.holds(r) for r in group):
            satisfied.append("any:" + "|".join(group))
        else:
            outstanding.append("any:" + "|".join(group))
    human_required = any(r in HUMAN_ONLY for r in outstanding)
    return Decision("verified" if not outstanding else "unverified", policy.version, rule.id, satisfied, outstanding,
                    human_required)


def migration_holds(old: Decision, new_policy: VerificationPolicy, category: str, ev: Evidence,
                    study_type: str | None = None) -> tuple[bool, Decision]:
    """A historical decision stays usable only if its recorded evidence satisfies the new rule (proof by
    re-evaluation); a stricter human requirement can never be met by a model-only history."""
    new = evaluate(new_policy, category, ev, study_type)
    return new.status == "verified", new
