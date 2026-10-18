"""M4 research intelligence tables.

Global reference tables hold only shareable, rights-cleared bibliographic metadata (never abstracts under
publisher copyright, uploads, notes, searches, passages, judgments or embeddings). Everything a tenant derives
lives in tenant-owned tables protected by RLS.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, GlobalMixin, TenantMixin

EMBED_DIM = 384


# --------------------------------------------------------------------------- global reference
class GlobalPaper(Base, GlobalMixin):
    __tablename__ = "global_papers"
    __scope__ = "global"
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(300))
    type: Mapped[str | None] = mapped_column(String(80))
    metadata_license: Mapped[str] = mapped_column(String(120))
    attribution: Mapped[str | None] = mapped_column(Text)
    source_provider: Mapped[str] = mapped_column(String(40))
    source_record_hash: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column()
    record_version: Mapped[int] = mapped_column(Integer, default=1)


class GlobalPaperIdentifier(Base, GlobalMixin):
    __tablename__ = "global_paper_identifiers"
    __scope__ = "global"
    __table_args__ = (UniqueConstraint("scheme", "value"),)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("global_papers.id"), index=True)
    scheme: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(300))


class VerificationPolicyRecord(Base, GlobalMixin):
    """Immutable published claim-verification policy versions (product policy, global)."""

    __tablename__ = "verification_policies"
    __scope__ = "global"
    version: Mapped[str] = mapped_column(String(60), unique=True)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    published_by: Mapped[str] = mapped_column(String(200))
    supersedes: Mapped[str | None] = mapped_column(String(60))


# --------------------------------------------------------------------------- tenant research records
class SearchRun(Base, TenantMixin):
    __tablename__ = "search_runs"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    purpose: Mapped[str] = mapped_column(String(30), default="scoping")  # scoping | method_stage | systematic
    query: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    providers_requested: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    provider_status: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    executed_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="queued")
    record_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    retrieved_count: Mapped[int] = mapped_column(Integer, default=0)
    protocol_id: Mapped[uuid.UUID | None] = mapped_column()


class TenantPaperRecord(Base, TenantMixin):
    __tablename__ = "tenant_paper_records"
    __table_args__ = (Index("uq_tenant_paper_doi", "project_id", "doi", unique=True, postgresql_where="doi IS NOT NULL"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    global_paper_id: Mapped[uuid.UUID | None] = mapped_column()
    doi: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    abstract_rights: Mapped[str] = mapped_column(String(60), default="unknown")
    license: Mapped[str | None] = mapped_column(Text)
    open_access: Mapped[bool | None] = mapped_column(Boolean)
    fulltext_locations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    fulltext_status: Mapped[str] = mapped_column(String(30), default="none")
    fulltext_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    fulltext_text_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    rights: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    identity_status: Mapped[str] = mapped_column(String(20), default="unverified")
    identity_verification: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sources: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    origin: Mapped[str] = mapped_column(String(20), default="search")  # search | manual | upload
    notes: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(60))
    retracted: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by: Mapped[str] = mapped_column(String(200))


class SearchResult(Base, TenantMixin):
    __tablename__ = "search_results"
    search_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("search_runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    rank: Mapped[int] = mapped_column(Integer)
    external_id: Mapped[str] = mapped_column(String(400))
    doi: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_paper_records.id"), index=True)


class ScreeningDecision(Base, TenantMixin):
    __tablename__ = "screening_decisions"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_paper_records.id"), index=True)
    stage: Mapped[str] = mapped_column(String(20))  # title_abstract | full_text
    decision: Mapped[str] = mapped_column(String(20))  # include | exclude | maybe
    reason: Mapped[str] = mapped_column(Text)
    criteria: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    method: Mapped[str] = mapped_column(String(20), default="human")
    decided_by: Mapped[str] = mapped_column(String(200))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    method_instance_id: Mapped[uuid.UUID | None] = mapped_column()


class EvidencePassage(Base, TenantMixin):
    __tablename__ = "evidence_passages"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_paper_records.id"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    quote_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_kind: Mapped[str] = mapped_column(String(20))  # fulltext | abstract | researcher_quote
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    source_hash: Mapped[str | None] = mapped_column(String(64))
    verified_in_source: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_method: Mapped[str] = mapped_column(String(20))  # deterministic | model_assisted | human
    extracted_by: Mapped[str] = mapped_column(String(200))
    extraction_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    freshness: Mapped[str] = mapped_column(String(10), default="current")


class Claim(Base, TenantMixin):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("project_id", "claim_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    claim_key: Mapped[str] = mapped_column(String(30))
    proposition: Mapped[str] = mapped_column(Text)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    kind: Mapped[str] = mapped_column(String(30))  # literature | observed_result | interpretation | hypothesis | limitation
    category: Mapped[str] = mapped_column(String(30))
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="unverified")
    confidence_rationale: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column()
    superseded_by: Mapped[uuid.UUID | None] = mapped_column()
    created_by: Mapped[str] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(30), default="researcher")  # researcher | extracted | writer
    decision: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    gate_eligible: Mapped[bool] = mapped_column(Boolean, default=False)


class ClaimSupport(Base, TenantMixin):
    """One evidence relationship and its verification record."""

    __tablename__ = "claim_support"
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id"), index=True)
    passage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_passages.id"), index=True)
    paper_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant_paper_records.id"))
    result_ref: Mapped[str | None] = mapped_column(String(200))
    relation: Mapped[str] = mapped_column(String(20))  # supports | contradicts | qualifies | closest_work
    bibliographic_identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    passage_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    claim_support_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class VerificationRecord(Base, TenantMixin):
    """Every identity/passage/support check: method, verifier identity/version, evidence, uncertainty."""

    __tablename__ = "verification_records"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id"), index=True)
    support_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claim_support.id"), index=True)
    paper_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant_paper_records.id"), index=True)
    check: Mapped[str] = mapped_column(String(40))  # identity | passage | support | strength | contradiction | closest_work | human_judgment | authoritative_source
    outcome: Mapped[str] = mapped_column(String(30))
    method: Mapped[str] = mapped_column(String(20))
    verifier: Mapped[str] = mapped_column(String(200))
    verifier_version: Mapped[str] = mapped_column(String(80))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    uncertainty: Mapped[str | None] = mapped_column(Text)
    requires_human_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    source_version_hash: Mapped[str | None] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class ClaimDecision(Base, TenantMixin):
    """Policy-evaluated status history (old decisions are retained when a policy changes)."""

    __tablename__ = "claim_decisions"
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id"), index=True)
    policy_version: Mapped[str] = mapped_column(String(60))
    rule_id: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    satisfied: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    outstanding: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    human_required: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(30), default="current")  # current | needs_reassessment | superseded | migrated
    migrated_from: Mapped[uuid.UUID | None] = mapped_column()
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    decided_by: Mapped[str] = mapped_column(String(200))


class LiteratureCoverageAssessment(Base, TenantMixin):
    __tablename__ = "literature_coverage_assessments"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    assessment_version: Mapped[int] = mapped_column(Integer)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    coverage_level: Mapped[str] = mapped_column(String(20))
    rationale: Mapped[str] = mapped_column(Text)
    limitations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    message: Mapped[str] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    inputs_hash: Mapped[str] = mapped_column(String(64))


class ProviderConnection(Base, TenantMixin):
    __tablename__ = "provider_connections"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    credential_secret_id: Mapped[uuid.UUID | None] = mapped_column()
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    terms_review_version: Mapped[str | None] = mapped_column(String(60))
    consent_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | revoked | exhausted | invalid
    last_check_at: Mapped[datetime | None] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column()
    quota: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# --------------------------------------------------------------------------- opportunities (M4 advisory)
class Opportunity(Base, TenantMixin):
    __tablename__ = "opportunities"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    set_artifact_id: Mapped[uuid.UUID] = mapped_column()
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    research_question: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    closest_work: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    novelty_caveat: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | selected | dismissed
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class PaperRationale(Base, TenantMixin):
    __tablename__ = "paper_rationales"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    rationale_version: Mapped[int] = mapped_column(Integer, default=1)
    problem: Mapped[str] = mapped_column(Text)
    gap: Mapped[str] = mapped_column(Text)
    gap_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    importance_to_venue: Mapped[str] = mapped_column(Text)
    research_question: Mapped[str] = mapped_column(Text)
    intended_contribution: Mapped[str] = mapped_column(Text)
    success_criterion: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | researcher_edited | approved
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    edited_by: Mapped[uuid.UUID | None] = mapped_column()
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class StudyTypeRecommendation(Base, TenantMixin):
    __tablename__ = "study_type_recommendations"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    study_type: Mapped[str] = mapped_column(String(40))
    venue_category: Mapped[str] = mapped_column(String(40))
    fit_rationale: Mapped[str] = mapped_column(Text)
    track_accepts: Mapped[str] = mapped_column(String(20))  # yes | no | unknown
    track_rule_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    required_inputs: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    reporting_standard: Mapped[str | None] = mapped_column(Text)
    blockers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    method_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    method_availability: Mapped[str] = mapped_column(Text)
    advisory: Mapped[bool] = mapped_column(Boolean, default=True)


class FeasibilityAssessment(Base, TenantMixin):
    __tablename__ = "research_feasibility_assessments"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id"), index=True)
    assessment_version: Mapped[int] = mapped_column(Integer, default=1)
    deadlines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    estimates: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cost_estimate: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    constraints: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    assumptions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    status: Mapped[str] = mapped_column(String(20))
    uncertainty: Mapped[str] = mapped_column(Text)
    slack_days: Mapped[float | None] = mapped_column(Float)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
