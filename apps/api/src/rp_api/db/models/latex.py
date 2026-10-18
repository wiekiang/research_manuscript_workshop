"""M3 template register and compile runs (tenant-owned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class Template(Base, TenantMixin):
    __tablename__ = "templates"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    mode: Mapped[str] = mapped_column(String(20))  # submission | camera_ready
    origin: Mapped[str] = mapped_column(String(30))  # official_link | researcher_supplied
    source_url: Mapped[str | None] = mapped_column(String(2048))
    declared_origin: Mapped[str | None] = mapped_column(Text)
    license_note: Mapped[str | None] = mapped_column(Text)
    overleaf_export_allowed: Mapped[bool | None] = mapped_column(Boolean)
    archive_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    manifest_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    archive_hash: Mapped[str | None] = mapped_column(String(64))
    family: Mapped[str | None] = mapped_column(String(40))
    class_name: Mapped[str | None] = mapped_column(String(80))
    version_label: Mapped[str | None] = mapped_column(String(120))
    bib_modes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    bibtex_style: Mapped[str | None] = mapped_column(String(120))
    requires_generation: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="analyzing")  # analyzing|rejected|unsupported|validated|confirmed|failed
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    unsupported_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    cfp_consistency: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    retrieved_at: Mapped[datetime | None] = mapped_column()
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column()
    confirmed_at: Mapped[datetime | None] = mapped_column()


class TemplateFile(Base, TenantMixin):
    __tablename__ = "template_files"
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("templates.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(40))
    protected: Mapped[bool] = mapped_column(Boolean, default=False)


class CompileRun(Base, TenantMixin):
    __tablename__ = "compile_runs"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("templates.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))  # sample | manuscript | package
    manuscript_version_id: Mapped[uuid.UUID | None] = mapped_column()
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30))
    report_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    pdf_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    log_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    source_bundle_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    pages: Mapped[int | None] = mapped_column()
    errors: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    freshness: Mapped[str] = mapped_column(String(10), default="current")
