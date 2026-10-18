"""M7 review, compliance and integrity tables (tenant-owned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class ReviewRound(Base, TenantMixin):
    __tablename__ = "review_rounds"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    manuscript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscripts.id"), index=True)
    manuscript_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscript_versions.id"))
    manuscript_version_number: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    functions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | complete | failed
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    meta_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    requested_by: Mapped[str] = mapped_column(String(200))


class ReviewReport(Base, TenantMixin):
    """Frozen once written; a reviewer never sees another function's report before its own is frozen."""

    __tablename__ = "review_reports"
    __table_args__ = (UniqueConstraint("round_id", "function"),)
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_rounds.id"), index=True)
    function: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))  # performed | partial | not_performed
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    assessed_ok: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ReviewFinding(Base, TenantMixin):
    __tablename__ = "review_findings"
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_rounds.id"), index=True)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_reports.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    function: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    check: Mapped[str] = mapped_column(Text)
    proposed_fix: Mapped[str | None] = mapped_column(Text)
    span_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    claim_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    artifact_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    rule_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String(30), default="open")  # open | fixed | accepted_risk | rejected_with_reason
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_in_version: Mapped[int | None] = mapped_column(Integer)


class ClaimCheckRecord(Base, TenantMixin):
    """Citation/evidence check of one claim/evidence pair and its linked spans; reusable while inputs match."""

    __tablename__ = "claim_check_records"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_rounds.id"), index=True)
    claim_key: Mapped[str] = mapped_column(String(40))
    check_key: Mapped[str] = mapped_column(String(64), index=True)
    critical: Mapped[bool] = mapped_column(Boolean)
    selection: Mapped[str] = mapped_column(String(20))  # critical | sampled
    source_status: Mapped[str] = mapped_column(String(20))
    source_detail: Mapped[str] = mapped_column(Text)
    meaning: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    method: Mapped[str] = mapped_column(String(30))  # deterministic+model_assisted | deterministic
    reused_from: Mapped[uuid.UUID | None] = mapped_column()


class ReviewRevision(Base, TenantMixin):
    __tablename__ = "review_revisions"
    __table_args__ = (UniqueConstraint("manuscript_id", "cycle"),)
    manuscript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscripts.id"), index=True)
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_rounds.id"))
    cycle: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[uuid.UUID] = mapped_column()
    finding_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    sections: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class IntegrityReport(Base, TenantMixin):
    __tablename__ = "integrity_reports"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    manuscript_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscript_versions.id"))
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    engine_version: Mapped[str] = mapped_column(String(40))
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | complete


class CheckDecision(Base, TenantMixin):
    """Signed human decision on a warning/manual_check item (integrity or compliance). Append-only."""

    __tablename__ = "check_decisions"
    __scope__ = "tenant_append_only"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    scope: Mapped[str] = mapped_column(String(20))  # integrity | compliance
    report_id: Mapped[uuid.UUID] = mapped_column(index=True)
    check_id: Mapped[str] = mapped_column(String(120))
    decision: Mapped[str] = mapped_column(String(30))  # accepted_risk | resolved | not_applicable
    rationale: Mapped[str] = mapped_column(Text)
    declaration_text: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID] = mapped_column()
    decided_role: Mapped[str] = mapped_column(String(20))
