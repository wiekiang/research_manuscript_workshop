from __future__ import annotations

from enum import StrEnum


class ProjectState(StrEnum):
    CREATED = "CREATED"
    TARGET_REVIEW = "TARGET_REVIEW"
    DIRECTION_REVIEW = "DIRECTION_REVIEW"
    PROTOCOL_REVIEW = "PROTOCOL_REVIEW"
    RESEARCH_ACTIVE = "RESEARCH_ACTIVE"
    OUTCOME_REVIEW = "OUTCOME_REVIEW"
    DRAFTING = "DRAFTING"
    SCIENTIFIC_REVIEW = "SCIENTIFIC_REVIEW"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    FINAL_APPROVAL = "FINAL_APPROVAL"
    APPROVED_FOR_EXPORT = "APPROVED_FOR_EXPORT"
    PACKAGE_READY = "PACKAGE_READY"
    # Overlays (resume state saved on the project row)
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class TenantRole(StrEnum):
    WORKSPACE_ADMIN = "workspace_admin"
    MEMBER = "member"


class ProjectRole(StrEnum):
    OWNER = "owner"
    COAUTHOR = "coauthor"
    REVIEWER = "reviewer"


class ActorType(StrEnum):
    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    WAITING_HUMAN = "waiting_human"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATES = {TaskState.SUCCEEDED, TaskState.FAILED_TERMINAL, TaskState.CANCELLED}


class ReservationStatus(StrEnum):
    RESERVED = "ARTIFACT_RESERVED"
    CONTENT_UPLOADED = "CONTENT_UPLOADED"
    HASH_VERIFIED = "HASH_VERIFIED"
    COMMITTED = "ARTIFACT_COMMITTED"
    EXPIRED = "EXPIRED"
    CONFLICT = "CONFLICT"


class ArtifactStatus(StrEnum):
    COMMITTED = "ARTIFACT_COMMITTED"
    AVAILABLE = "AVAILABLE_TO_WORKFLOW"


class Freshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class Gate(StrEnum):
    CFP = "CFP"
    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    H4 = "H4"


class ApprovalStatus(StrEnum):
    VALID = "valid"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class LedgerCategory(StrEnum):
    IDEA = "idea"
    QUESTION_REFINEMENT = "question_refinement"
    METHODOLOGY_EDIT = "methodology_edit"
    SUPPLIED_DATA = "supplied_data"
    ANALYSIS = "analysis"
    INTERPRETATION = "interpretation"
    MANUSCRIPT_CHANGE = "manuscript_change"
    THEORETICAL_WORK = "theoretical_work"
    OTHER = "other"


class VerificationMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_ASSISTED = "model_assisted"
    HUMAN = "human"


class ClaimKind(StrEnum):
    LITERATURE = "literature"
    OBSERVED_RESULT = "observed_result"
    INTERPRETATION = "interpretation"
    HYPOTHESIS = "hypothesis"
    LIMITATION = "limitation"


class ClaimStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONTESTED = "contested"
    REJECTED = "rejected"


class ClaimCategory(StrEnum):
    """Policy category used by the verification policy (critical categories need human-inspectable support)."""

    IDENTITY = "identity"
    DESCRIPTIVE = "descriptive"
    NUMERICAL = "numerical"
    NOVELTY = "novelty"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    ETHICS_POLICY = "ethics_policy"
    CENTRAL_CONCLUSION = "central_conclusion"


CRITICAL_CLAIM_CATEGORIES = {
    ClaimCategory.NUMERICAL,
    ClaimCategory.NOVELTY,
    ClaimCategory.COMPARATIVE,
    ClaimCategory.CAUSAL,
    ClaimCategory.ETHICS_POLICY,
    ClaimCategory.CENTRAL_CONCLUSION,
}


class AssuranceLevel(StrEnum):
    DECLARED = "declared"
    INTERNALLY_CONSISTENT = "internally_consistent"
    INDEPENDENTLY_CHECKED = "independently_checked"
    REPRODUCED = "reproduced"


ASSURANCE_ORDER = [
    AssuranceLevel.DECLARED,
    AssuranceLevel.INTERNALLY_CONSISTENT,
    AssuranceLevel.INDEPENDENTLY_CHECKED,
    AssuranceLevel.REPRODUCED,
]


class FindingSeverity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    SUGGESTION = "suggestion"


class FindingResolution(StrEnum):
    OPEN = "open"
    FIXED = "fixed"
    ACCEPTED_RISK = "accepted_risk"
    REJECTED_WITH_REASON = "rejected_with_reason"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    MANUAL_CHECK = "manual_check"
    NOT_PERFORMED = "not_performed"
    WARNING = "warning"


class ReadinessStage(StrEnum):
    RESEARCH_PROPOSAL = "research_proposal"
    RESEARCH_IN_PROGRESS = "research_in_progress"
    MANUSCRIPT_DRAFT = "manuscript_draft"
    SCIENTIFIC_REVIEW_COMPLETE = "scientific_review_complete"
    COMPLIANCE_CHECKED = "compliance_checked"
    APPROVED_FOR_EXPORT = "approved_for_export"
    SUBMISSION_READY_PACKAGE = "submission_ready_package"
    NOT_SUBMISSION_READY = "not_submission_ready"


class FeasibilityStatus(StrEnum):
    FEASIBLE = "feasible"
    AT_RISK = "at_risk"
    INFEASIBLE = "infeasible"


class OutcomeStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_SUPPORTED = "not_supported"
    INCONCLUSIVE = "inconclusive"


class GapResolution(StrEnum):
    ADDRESSED = "addressed"
    PARTIALLY_ADDRESSED = "partially_addressed"
    NOT_ADDRESSED = "not_addressed"
    INCONCLUSIVE = "inconclusive"


class RuleStatus(StrEnum):
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    NEEDS_HUMAN_RESOLUTION = "needs_human_resolution"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class DeadlineKind(StrEnum):
    ABSTRACT_REGISTRATION = "abstract_registration"
    FULL_PAPER = "full_paper"
    SUPPLEMENTARY = "supplementary"
    REBUTTAL = "rebuttal"
    NOTIFICATION = "notification"
    CAMERA_READY = "camera_ready"
    AUTHOR_REGISTRATION = "author_registration"
    ARTIFACT = "artifact"
    OTHER = "other"


class IntendedAction(StrEnum):
    NEW_SUBMISSION = "new_submission"
    ABSTRACT_REGISTRATION = "abstract_registration"
    REBUTTAL = "rebuttal"
    CAMERA_READY = "camera_ready"
    ARTIFACT_SUBMISSION = "artifact_submission"
    AUTHOR_REGISTRATION = "author_registration"


class StudyType(StrEnum):
    EMPIRICAL_QUANTITATIVE = "empirical_quantitative"
    SECONDARY_DATA = "secondary_data"
    EMPIRICAL_QUALITATIVE = "empirical_qualitative"
    THEORETICAL = "theoretical"
    METHODOLOGICAL = "methodological"
    NARRATIVE_REVIEW = "narrative_review"
    SYSTEMATIC_REVIEW = "systematic_review"
    META_ANALYSIS = "meta_analysis"
    MAPPING_REVIEW = "mapping_review"
    SCOPING_REVIEW = "scoping_review"
    TERTIARY_REVIEW = "tertiary_review"
    COMPUTATIONAL_EXPERIMENT = "computational_experiment"
