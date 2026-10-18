"""M5 scientific contribution tables (tenant-owned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class MethodWorkflowInstance(Base, TenantMixin):
    __tablename__ = "method_workflow_instances"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    definition_key: Mapped[str] = mapped_column(String(120))
    study_type: Mapped[str] = mapped_column(String(40))
    definition_version: Mapped[int] = mapped_column(Integer)
    venue_category: Mapped[str] = mapped_column(String(40))
    enabled_for_submission_ready: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | superseded
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column()
    selection_rationale: Mapped[str | None] = mapped_column(Text)
    override_of_recommendation: Mapped[bool] = mapped_column(Boolean, default=False)
    track_accepts: Mapped[str] = mapped_column(String(20), default="unknown")
    selected_by: Mapped[uuid.UUID] = mapped_column()
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column()
    reuse_decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    frozen_at: Mapped[datetime | None] = mapped_column()


class Protocol(Base, TenantMixin):
    __tablename__ = "protocols"
    __table_args__ = (UniqueConstraint("method_instance_id", "version_number"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    method_instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("method_workflow_instances.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | frozen | superseded
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ethics_rights: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    compute_estimate: Mapped[str | None] = mapped_column(Text)
    cost_estimate_cents: Mapped[int | None] = mapped_column(Integer)
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)
    amendment_rationale: Mapped[str | None] = mapped_column(Text)
    after_data_inspection: Mapped[bool] = mapped_column(Boolean, default=False)
    frozen_at: Mapped[datetime | None] = mapped_column()
    frozen_by: Mapped[uuid.UUID | None] = mapped_column()
    review_status: Mapped[str] = mapped_column(String(20), default="not_requested")  # not_requested|requested|performed|not_performed|waived
    review_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    review_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    review_waiver_rationale: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column()


class Contribution(Base, TenantMixin):
    __tablename__ = "contributions"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    contribution_type: Mapped[str] = mapped_column(String(40))
    workspace_field: Mapped[str | None] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(400))
    text: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))
    license: Mapped[str | None] = mapped_column(String(200))
    visibility: Mapped[str] = mapped_column(String(20))  # public | private | restricted
    pii_classification: Mapped[str] = mapped_column(String(20))  # none | pseudonymized | personal | sensitive
    rights_statement: Mapped[str | None] = mapped_column(Text)
    relation_to_protocol: Mapped[str | None] = mapped_column(Text)
    protocol_id: Mapped[uuid.UUID | None] = mapped_column()
    scan_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class MethodStageOutput(Base, TenantMixin):
    __tablename__ = "method_stage_outputs"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    method_instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("method_workflow_instances.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("protocols.id"), index=True)
    stage_id: Mapped[str] = mapped_column(String(60))
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validator_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20))  # validated | failed | stale
    submitted_by: Mapped[str] = mapped_column(String(200))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class ResultManifestRecord(Base, TenantMixin):
    __tablename__ = "result_manifests"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    method_instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("method_workflow_instances.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("protocols.id"))
    stage_id: Mapped[str | None] = mapped_column(String(60))
    result_key: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(400))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    attested_by: Mapped[uuid.UUID | None] = mapped_column()
    origin: Mapped[str] = mapped_column(String(20), default="researcher_supplied")  # researcher_supplied | platform_run
    status: Mapped[str] = mapped_column(String(20), default="submitted")  # submitted | assessed | stale
    assurance_level: Mapped[str | None] = mapped_column(String(30))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class ResultAssessmentRecord(Base, TenantMixin):
    __tablename__ = "result_assessments"
    result_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("result_manifests.id"), index=True)
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    assurance_level: Mapped[str] = mapped_column(String(30))
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    missing: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    impossible_checks: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    wording_limits: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    blockers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    assessor: Mapped[str] = mapped_column(String(120))
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class ContributionValidationRow(Base, TenantMixin):
    __tablename__ = "contribution_validation_rows"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    method_instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("method_workflow_instances.id"), index=True)
    rq_index: Mapped[int] = mapped_column(Integer)
    research_question: Mapped[str] = mapped_column(Text)
    intended_novelty: Mapped[str] = mapped_column(Text)
    intended_contribution: Mapped[str] = mapped_column(Text)
    success_criterion: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    validity_assessment: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(30))
    limitations: Mapped[str | None] = mapped_column(Text)
    h3_decision: Mapped[str | None] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(20), default="draft")  # draft | researcher_reviewed
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column()
    reviewed_at: Mapped[datetime | None] = mapped_column()
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class GapResolutionAssessment(Base, TenantMixin):
    __tablename__ = "gap_resolution_assessments"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    method_instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("method_workflow_instances.id"))
    status: Mapped[str] = mapped_column(String(30))
    supporting_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    explanation: Mapped[str] = mapped_column(Text)
    assessed_by: Mapped[uuid.UUID] = mapped_column()
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
