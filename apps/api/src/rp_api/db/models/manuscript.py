"""M6 manuscript tables (tenant-owned)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class Manuscript(Base, TenantMixin):
    __tablename__ = "manuscripts"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True, unique=True)
    title: Mapped[str] = mapped_column(Text)
    study_type: Mapped[str | None] = mapped_column(String(40))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column()
    current_version_number: Mapped[int] = mapped_column(Integer, default=0)


class ManuscriptVersion(Base, TenantMixin):
    __tablename__ = "manuscript_versions"
    __table_args__ = (UniqueConstraint("manuscript_id", "version_number"),)
    manuscript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscripts.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column()
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(30))  # initial | human_edit | candidate_applied | merge
    candidate_id: Mapped[uuid.UUID | None] = mapped_column()
    brief_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200))
    checks_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ManuscriptSpan(Base, TenantMixin):
    __tablename__ = "manuscript_spans"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscript_versions.id"), index=True)
    section_key: Mapped[str] = mapped_column(String(60))
    span_id: Mapped[str] = mapped_column(String(40), index=True)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    claim_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    result_keys: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    origin: Mapped[str] = mapped_column(String(10))
    protected: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="ok")  # ok | issues | stale
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class GenerationCandidate(Base, TenantMixin):
    __tablename__ = "generation_candidates"
    manuscript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscripts.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    base_version_id: Mapped[uuid.UUID] = mapped_column()
    base_content_hash: Mapped[str] = mapped_column(String(64))
    input_manifest_hash: Mapped[str] = mapped_column(String(64))
    brief_artifact_id: Mapped[uuid.UUID] = mapped_column()
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    sections: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | ready | stale | applied | merged | rejected | failed
    rationale: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    conflicts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class BibliographyEntry(Base, TenantMixin):
    __tablename__ = "bibliography_entries"
    __table_args__ = (UniqueConstraint("project_id", "cite_key"), UniqueConstraint("project_id", "paper_id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_paper_records.id"))
    cite_key: Mapped[str] = mapped_column(String(120))
    bibtex: Mapped[str] = mapped_column(Text)
    identity_status: Mapped[str] = mapped_column(String(20))
    identity_hash: Mapped[str] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
