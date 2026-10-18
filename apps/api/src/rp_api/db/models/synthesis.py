"""M10 evidence-synthesis and qualitative-analysis tables (tenant-owned)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class ExtractionRecord(Base, TenantMixin):
    """Per included study: extraction form values (each linked to a passage or marked not reported), appraisal,
    effect estimate (meta-analysis), charting (mapping/scoping) and listed primary studies (tertiary)."""

    __tablename__ = "extraction_records"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_paper_records.id"), index=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    appraisal: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    effect: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    charting: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    primary_studies: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    recorded_by: Mapped[uuid.UUID] = mapped_column()
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class SynthesisRecord(Base, TenantMixin):
    __tablename__ = "synthesis_records"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(30))  # flow | meta_analysis | map | overlap | appendix
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    inputs_hash: Mapped[str] = mapped_column(String(64))
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class QualCode(Base, TenantMixin):
    __tablename__ = "qual_codes"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(index=True)
    code: Mapped[str] = mapped_column(String(120))
    definition: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column()


class QualSegment(Base, TenantMixin):
    """A coded excerpt; the quote must be found verbatim in the source contribution's text (audit trail)."""

    __tablename__ = "qual_segments"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    code_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qual_codes.id"), index=True)
    contribution_id: Mapped[uuid.UUID] = mapped_column(index=True)
    quote: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    memo: Mapped[str | None] = mapped_column(Text)
    coded_by: Mapped[uuid.UUID] = mapped_column()


class QualTheme(Base, TenantMixin):
    __tablename__ = "qual_themes"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    protocol_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    code_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    interpretation: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column()
