"""M8 submission preparation tables (tenant-owned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class AuthorEntry(Base, TenantMixin):
    __tablename__ = "author_entries"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    record_version: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    affiliations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    orcid: Mapped[str | None] = mapped_column(String(20))
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    corresponding: Mapped[bool] = mapped_column(Boolean, default=False)
    contribution_roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    contribution_statement: Mapped[str] = mapped_column(Text)
    competing_interests: Mapped[str] = mapped_column(Text)
    funding: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    artifact_id: Mapped[uuid.UUID] = mapped_column()


class AuthorAssent(Base, TenantMixin):
    """An author's approval of one exact manuscript version. Append-only; never inferred."""

    __tablename__ = "author_assents"
    __scope__ = "tenant_append_only"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    author_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("author_entries.id"), index=True)
    manuscript_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscript_versions.id"))
    manuscript_hash: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(30))  # in_product | offline_attestation
    statement: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    evidence_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    recorded_by: Mapped[uuid.UUID] = mapped_column()


class DisclosureRecord(Base, TenantMixin):
    __tablename__ = "disclosure_records"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    record_version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column()


class EligibilityAssessment(Base, TenantMixin):
    __tablename__ = "eligibility_assessments"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    completed_prerequisites: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    schedule_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    evaluator_version: Mapped[str] = mapped_column(String(40))
    assessed_by: Mapped[str] = mapped_column(String(200))


class ReadinessAssessment(Base, TenantMixin):
    __tablename__ = "readiness_assessments"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    manuscript_version_id: Mapped[uuid.UUID | None] = mapped_column()
    stage: Mapped[str] = mapped_column(String(40))
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    manual_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    limitations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    assessor: Mapped[str] = mapped_column(String(200))
    assessor_version: Mapped[str] = mapped_column(String(40))


class ExportPackage(Base, TenantMixin):
    __tablename__ = "export_packages"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="building")  # building | built | verified | failed
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    h4_approval_id: Mapped[uuid.UUID | None] = mapped_column()
    content_manifest_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    content_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    checksum: Mapped[str | None] = mapped_column(String(64))
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    problems: Mapped[list[str]] = mapped_column(JSONB, default=list)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
